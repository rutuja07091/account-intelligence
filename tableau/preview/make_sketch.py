import duckdb, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import gridspec
from matplotlib.colors import TwoSlopeNorm
c=duckdb.connect()
for t in ['accounts','physician_activity','account_monthly']:
    c.execute(f"create view {t} as select * from read_csv_auto('tableau/data/{t}.csv')")
T='Ohio Valley'
acc=c.sql(f"select account_name, cases_last_90d*1.0/est_ccta_90d u, (cases_last_90d-cases_prior_90d)*1.0/nullif(cases_prior_90d,0) chg from accounts where territory='{T}' order by u").df()
qp=c.sql(f"select physician_name||'  ('||account_name||')' lbl, cases_prior_90d from physician_activity where territory='{T}' and days_since_last_case>=60 and lifetime_cases>=5 order by cases_prior_90d desc limit 10").df().iloc[::-1]
ramp=c.sql(f"select account_name, months_since_activation m, cases from account_monthly where activation_cohort='Activated in last 12 months' and territory='{T}' order by 1,2").df()
avg=c.sql(f"select months_since_activation m, sum(cases)*1.0/count(distinct account_id) v from account_monthly where activation_cohort='Activated in last 12 months' and territory='{T}' group by 1 having count(distinct account_id)>=3 order by 1").df()
k=c.sql(f"select count(*), sum(cases_last_90d), sum(cases_last_90d)*1.0/sum(est_ccta_90d), (sum(cases_last_90d)-sum(cases_prior_90d))*1.0/sum(cases_prior_90d) from accounts where territory='{T}'").fetchone()
nq=c.sql(f"select count(*) from physician_activity where territory='{T}' and days_since_last_case>=60 and lifetime_cases>=5").fetchone()[0]

ink="#16233A"; mute="#5B6B7F"; red="#B3122E"; grid="#D9E1E8"
plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.edgecolor":grid,"axes.labelcolor":mute,"xtick.color":mute,"ytick.color":mute})
fig=plt.figure(figsize=(16,10),dpi=110,facecolor="#F6F8FA")
gs=gridspec.GridSpec(3,2,height_ratios=[0.16,1,1],width_ratios=[1,1.05],hspace=0.35,wspace=0.42,left=0.17,right=0.97,top=0.88,bottom=0.06)
fig.text(0.03,0.955,"Account Intelligence",fontsize=20,weight="bold",color=ink)
fig.text(0.03,0.925,f"Territory: {T}   |   Quiet threshold: 60 days   |   Synthetic data, snapshot 2026-09-30",fontsize=10.5,color=mute)
fig.text(0.97,0.955,"REFERENCE SKETCH  -  build the real dashboard in Tableau",fontsize=9,color=red,ha="right")
kp=fig.add_subplot(gs[0,:]); kp.axis("off")
kpis=[("Accounts",f"{k[0]}"),("Cases, last 90 days",f"{k[1]:,}"),("Est. utilization",f"{k[2]:.1%}"),("Cases vs prior 90 days",f"{k[3]:+.1%}"),("Physicians gone quiet",f"{nq}")]
for i,(l,v) in enumerate(kpis):
    x=i/5
    kp.text(x+0.0,0.75,v,fontsize=22,weight="bold",color=red if i==4 else ink,transform=kp.transAxes)
    kp.text(x+0.0,0.05,l,fontsize=10,color=mute,transform=kp.transAxes)
a1=fig.add_subplot(gs[1:,0])
norm=TwoSlopeNorm(vmin=-0.6,vcenter=0,vmax=0.6); cmap=plt.get_cmap("PuOr")
a1.barh(acc.account_name,acc.u,color=[cmap(norm(x if x==x else 0)) for x in acc.chg])
a1.axvline(k[2],color=ink,lw=1,ls="--"); a1.text(k[2],len(acc)-0.3,f" territory avg {k[2]:.0%}",fontsize=8.5,color=ink,va="bottom")
a1.set_title("Estimated utilization by account (lowest first)\ncolor = cases vs prior 90 days, orange = declining",loc="left",fontsize=11,color=ink)
a1.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0)); a1.invert_yaxis(); a1.tick_params(axis="y",labelsize=8); a1.grid(axis="x",color=grid)
a2=fig.add_subplot(gs[1,1])
a2.barh(qp.lbl,qp.cases_prior_90d,color=red); a2.tick_params(axis="y",labelsize=8)
a2.set_title("Physicians gone quiet (60+ days, 5+ lifetime cases)\nbar = cases in the 90 days before that, volume at risk",loc="left",fontsize=11,color=ink); a2.grid(axis="x",color=grid)
a3=fig.add_subplot(gs[2,1])
for n,g in ramp.groupby("account_name"): a3.plot(g.m,g.cases,color="#AFC0D0",lw=1)
a3.plot(avg.m,avg.v,color=ink,lw=2.5,marker="o",ms=4,label="average per account")
a3.set_title("Ramp curves: accounts activated in the last 12 months\ngrey = each account, dark = average (months with 3+ accounts)",loc="left",fontsize=11,color=ink)
a3.set_xlabel("Months since go-live"); a3.set_ylabel("Cases per month"); a3.grid(color=grid); a3.legend(frameon=False,fontsize=8.5)
for ax in (a1,a2,a3):
    ax.set_facecolor("#FFFFFF")
    for s in ("top","right"): ax.spines[s].set_visible(False)
fig.savefig("tableau/preview/dashboard_sketch.png",facecolor=fig.get_facecolor())
print("ok")
