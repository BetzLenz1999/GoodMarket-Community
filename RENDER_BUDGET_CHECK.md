# Render budget check for GoodMarket (corrected for **Hobby New**)

## Correction

Tama ka — **walang fixed $7 price ang Hobby (New)**.

Hobby (New) is **$0/month workspace fee**, then you pay **compute costs per service** plus possible overages (like bandwidth).

## What the screenshot means

From the plan card:
- **$0/mo** (workspace subscription)
- **plus compute costs**
- Includes **5 GB bandwidth**, then **$0.15/GB** after
- Includes **2 custom domains**, then **$0.25/domain** after
- Up to **25 services**

So the monthly bill is not a flat Hobby fee. It is:

**Total = service compute + bandwidth overage + optional extras**

## Repo-based deployment fit

For this repo, deployment can be kept simple:
- Flask + Gunicorn backend
- Single `web` process in Procfile
- Supabase is external DB (so Render Postgres is optional, not required)

That means your cost floor can be low, but exact total depends on:
1) what compute instance size you choose, and
2) how much outbound traffic you use beyond 5 GB.

## Practical conclusion for your question

- If your workload is small, **pwede sa very low monthly cost** under Hobby New.
- If traffic grows, billing will rise from:
  - compute instance cost, and/or
  - bandwidth overage after 5 GB.

## Recommendation

1. Start with one web service only.
2. Monitor Render metrics for outbound GB every week.
3. Keep static assets compressed/cached.
4. Recompute monthly total after 2 weeks of real usage.

This gives an accurate real-world budget instead of assuming a fixed "$7" plan price.
