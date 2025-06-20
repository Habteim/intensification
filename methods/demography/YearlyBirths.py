""" YearlyBirths.py

Using output from AgeAtKthKid.py and NumberOfKids.py in conjunction with estimates
of the distribution of mother characteristic to estimate births per year. This is an 
intermediate step in the modeling, for comparison with quantities like the World Bank
birth rate, etc.  """
import sys
sys.path.append("..\\")
import survey

## For filepaths
import os

## I/O functionality is built on top
## of pandas
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

## Get the distribution functions
from survey.negative_binomial import pmf as nb_pmf
from survey.zero_inflated_nb import pmf as znb_pmf
from survey.ridge import log_normal_density as lognorm_pdf

def cms_to_datetime(a,d=15):
	assert (a >= 1).all(), "CMS format must be >= 1"
	years = 1900+((a-1)/12).astype(int)
	months = a - 12*(years-1900)
	dates = pd.to_datetime({"year":years,
							"month":months,
							"day":d})
	return dates

def axes_setup(axes):
	axes.spines["left"].set_position(("axes",-0.025))
	axes.spines["top"].set_visible(False)
	axes.spines["right"].set_visible(False)
	return

## For worldbank data
def get_raw_spreadsheet(root,fname,
						years=(2010,2019)):

	## I/O based on pandas with specific dtypes
	## for speed.
	columns = ["Country Name"]+[str(c) for c in range(*years)]
	dtypes = {c:np.float64 for c in columns[1:]}
	dtypes["Country Name"] = str
	df = pd.read_csv(root+fname,
					 skiprows=4,header=0,
					 usecols=columns,
					 dtype=dtypes)

	## Adjust country names to the WHO spreadsheet values
	## done manually here.
	adjustments = {"Yemen, Rep.":"yemen",
				   "Vietnam":"viet nam",
				   "Tanzania":"united republic of tanzania",
				   "Korea, Dem. People’s Rep.":"democratic people's republic of korea",
				   "Gambia, The":"gambia",
				   "Congo, Dem. Rep.":"democratic republic of the congo"}
	df["Country Name"] = df["Country Name"].apply(lambda x: adjustments.get(x,x))

	## Basic formatting
	df.columns = [c.lower().replace(" name","") for c in df.columns]
	df["country"] = df["country"].str.lower()

	return df

def to_spacetime(df,name):
	df = df.set_index("country").stack(dropna=False).reset_index()
	df.columns = ["country","year",name]
	return df

def GetBirthsSeries(root,
					years=(2010,2019),
					countries=None):

	""" Subroutine to get the raw WB spreadsheets (located in root) and to
		reshape it into a space-time dataframe, interpolate, and compute
		births. """

	## Get the raw data
	birthrate = get_raw_spreadsheet(root,fname="worldbank_crudebirthrate.csv",
									years=years)

	## Subset to specific countries
	if countries is not None:
		birthrate = birthrate.loc[birthrate["country"].isin(countries)]

	## Reshape both into space-time series
	birthrate = to_spacetime(birthrate,"br")

	## Convert to timestamps
	birthrate["time"] = pd.to_datetime({"year":birthrate["year"],
										"month":6,
										"day":15})

	return birthrate

def get_a_dhs(path,columns,convert_categoricals=True,add_survey=False):
	df = pd.read_stata(path,
					   columns=columns,
					   convert_categoricals=convert_categoricals)
	df["caseid"] = df["caseid"].str.strip()
	if add_survey:
		df["survey"] = path.split(os.path.sep)[1].lower()
	return df

def weighted_mean_var(x):
	avg = (x["v005"]*x["pr_birth_last_year"]).sum()
	var = ((x["v005"])*x["pr_birth_last_year"]*(1.-x["pr_birth_last_year"])).sum()
	out = pd.Series([avg,var],index=["avg","var"])
	return out

if __name__ == "__main__":

	## Get the demographic cell populations
	dist = pd.read_pickle("pickle_jar\\mom_distribution.pkl")
	dist["year"] = "year:"+(dist["year"].astype(str))
	print(dist)
	sys.exit()

	## Get the model outputs stratified by state
	age_at_kth_by_state = pd.read_pickle("pickle_jar\\lognormal_age_at_k_by_state.pkl")
	num_kids_by_state = pd.read_pickle("pickle_jar\\zero_inf_neg_bin_num_kids_by_state.pkl")

	## Loop over cells to compute distribution parameters
	## for all possible combinations.
	print("\nComputing estimates by cell...")
	k = np.arange(0,20)
	ages = np.arange(1,12*100+1)/12.
	pr_birth_last_year = np.zeros((len(dist),))
	_debug = False
	for i, r in dist.iterrows():

		## Subset to the right state
		num_kids = num_kids_by_state.loc[r.loc["state"]]
		age_at_kth = age_at_kth_by_state.loc[r.loc["state"]]

		## And get this state's dispersion parameters
		alpha = num_kids["alpha"].values[0]
		var = age_at_kth["var"].values[0]
	
		## Compute the number of kids distribution
		mom_x = r.loc[["v013","v025","v106","year"]]
		lr_mu_kids = num_kids.loc["intercept","lr_beta"]+\
					 num_kids.loc[mom_x.values,"lr_beta"].sum()
		nb_mu_kids = np.exp(num_kids.loc["intercept","nb_beta"]+\
							num_kids.loc[mom_x.values,"nb_beta"].sum())
		k_pmf = znb_pmf(k,lr_mu_kids,nb_mu_kids,alpha)
		k_pmf = k_pmf/(k_pmf.sum())

		## Compute age-at-birth distributions across the
		## number of kids
		mom_x = r.loc[["v025","v106","year"]]
		mu_k = age_at_kth.loc["intercept","beta"]+\
			   age_at_kth.loc[mom_x.values,"beta"].sum()
		mu_k += k*age_at_kth.loc["bord","beta"]
		age_dists = lognorm_pdf(ages[np.newaxis,:],
								mu_k[:,np.newaxis],
								var)
		age_dists = age_dists/(age_dists.sum(axis=1)[:,np.newaxis])

		## Weight the distributions by the probability of having 
		## k kids, removing 0 kids.
		age_dists = age_dists[1:,:]*(k_pmf[1:,np.newaxis])

		## Finally, calculated the expected number of children in the previous
		## year using the age-bin as an anchor.
		l, h = r.loc["v013"].split("-")
		total_pr_birth = age_dists[:,(int(l)-1)*12-1:(int(h)-1)*12].sum()
		#total_pr_birth *= 1.2 ## For experimenting with WP agreement

		if _debug and r.loc["v013"]=="25-29":

			## Set up colors
			cmap = plt.get_cmap("RdPu_r")
			colors = [cmap(i) for i in np.linspace(0.05,0.95,len(k))]

			## Kid distribution
			fig, axes = plt.subplots(figsize=(6,5))
			axes.spines["left"].set_visible(False)
			axes.spines["top"].set_visible(False)
			axes.spines["right"].set_visible(False)
			for i in range(len(k)):
				axes.bar([k[i]],[k_pmf[i]],width=0.8,
						 color=colors[i])
			axes.set_yticks([])
			axes.set_xlabel("Number of kids")
			fig.tight_layout()
			fig.savefig("_plots\\debug_kids.png",transparent=True)

			## Age at birth
			#age_dists = age_dists/(k_pmf[1:,np.newaxis])
			fig, axes = plt.subplots(figsize=(10,5))
			axes.spines["left"].set_visible(False)
			axes.spines["top"].set_visible(False)
			axes.spines["right"].set_visible(False)
			for i,a in enumerate(age_dists):
				axes.plot(ages,a,color=colors[i+1],lw=2,zorder=2,label=k[i+1])
			age_range = ages[(int(l)-1)*12-1:(int(h)-1)*12]
			axes.axvspan(age_range[0],age_range[-1],
						 facecolor="grey",edgecolor="None",alpha=0.5)
			axes.set_xlabel("Mom's age at birth")
			axes.set_ylim((0,None))
			axes.set_yticks([])
			fig.tight_layout()
			fig.savefig("_plots\\debug_age.png",transparent=True)
			plt.show()
			sys.exit()

		## Take the average over the 4 year bin (essentially uniformly distributing the
		## births over the age-bin) and correct (coarsely) for this being an estimate on
		## married women only.
		married_correction = 1.#-never_married[r.loc["v013"]]
		total_pr_birth *= (1./4.)*married_correction

		## Store the result
		pr_birth_last_year[i] = total_pr_birth

	## Add the results to your demographic cells
	dist["pr_birth_last_year"] = pr_birth_last_year
	dist["year"] = dist["year"].str.slice(start=5).astype(int)-1
	print("We find:")
	print(dist)

	## Append to the serialized distribution
	dist.to_pickle("pickle_jar\\mom_distribution_inf.pkl")

	## From which you can compute the births per 
	## married woman by year
	br = dist[["v005","year","pr_birth_last_year"]].copy()
	br = br.groupby("year").apply(weighted_mean_var)
	print("\nThat gives a birth rates like...")

	## Adjust to per 1k (which doesn't get the squared on variance
	## because v005 is the fraction of pop (so this is a change in units 
	## on the weights))
	br["avg"] *= 1000
	br["var"] *= 1000#**2
	br["std"] = np.sqrt(br["var"])
	print(br)

	## For comparison
	wb_br = GetBirthsSeries("..\\_open_data\\",
							countries=["nigeria"],
							years=(2009,2019))
	wb_br["year"] = wb_br["year"].astype(int)

	## Plot the results, etc.
	fig, axes = plt.subplots(figsize=(11,5))
	axes_setup(axes)
	axes.grid(color="grey",alpha=0.3)
	axes.plot(wb_br["year"],wb_br["br"],
			  marker="o",lw=2,ls="dashed",markersize=12,
			  color="k",label="World Bank",zorder=2)
	axes.errorbar(br.index,br["avg"].values,
				  yerr=br["std"].values,
				  color="xkcd:red wine",lw=1,ls="None")
	axes.plot(br["avg"],
			  marker="o",lw=2,ls="dashed",markersize=12,
			  color="xkcd:red wine",label="DHS-based models",zorder=2)
	axes.legend(loc=3,frameon=False)
	axes.set_ylabel("Crude birth rate")
	#axes.set_ylim((20,37))
	fig.tight_layout()
	fig.savefig("_plots\\br_compare.png")
	plt.show()