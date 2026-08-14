# Finsance public daily analysis

The scheduled workflow writes a public-safe artifact to
reports/finsance/daily_latest.json. It is an allow-list projection of an
AnalysisResult; private trading levels, current prices, raw responses and
provider payloads are not copied.

The target public route in the Finsance Website service is:

https://www.finsance.com/daily-stock-analysis

The route is SSR and reads the committed artifact only. It does not call
Gemini, OpenAI, Yahoo or yfinance during a page request. SEO indexing must wait
for an explicit freshness signal and the existing publication/compliance
review.

## AI and data settings

Keep secrets in GitHub Actions Secrets, never in source:

- GEMINI_API_KEY (primary; the workflow already maps GEMINI_MODEL)
- OPENAI_API_KEY (fallback)
- OPENAI_BASE_URL and OPENAI_MODEL when using an OpenAI-compatible endpoint
- LITELLM_FALLBACK_MODELS=gemini/<light-model>,openai/<configured-model> to
  make the fallback explicit and reduce Gemini quota collisions

The free path remains the default: yfinance, AkShare and Baostock are
available through the existing data-provider fallback chain. The existing
fundamentals pipeline may add earnings context when a free source returns it;
missing values remain unavailable.

FINSANCE_COMMERCIAL_MODE=false keeps the public artifact labelled as free
data. Set it to true only with FINSANCE_COMMERCIAL_PROVIDER configured and
after a licensing review. This switch annotates the artifact; it does not
silently turn on a paid provider.

## Automatic cross-repository push

The push is opt-in and disabled by default. In the
ZhuLinsen/daily_stock_analysis repository, add these Actions variables and
secret:

| Name | Kind | Value |
| --- | --- | --- |
| FINSANCE_PUBLICATION_ENABLED | Variable | true |
| FINSANCE_REPO | Variable | jamerskrs-lgtm/Finsance-Website |
| FINSANCE_BRANCH | Variable | main |
| GH_PAT | Secret | Fine-grained PAT with Contents read/write on the Finsance repo; `GITHUB_TOKEN` is the automatic source-repo token and cannot be used for this cross-repo push |

The workflow accepts `GH_PAT` as the cross-repo push secret (and keeps
`FINSANCE_REPO_TOKEN` as a backwards-compatible alias), checks out the target
repo, validates the schema and forbidden
fields, copies only content/quanttrade/daily_*.json plus checksums, and updates
the root `.render-quanttrade-trigger` marker. The marker is required because
the existing Render build filter ignores `content/**`; it makes the daily
commit trigger a rebuild without making every unrelated content commit do so.
Render must have auto-deploy-on-push enabled for the Finsance Website service;
that Render setting and DNS/production response still require live-console
verification.

To roll back, disable FINSANCE_PUBLICATION_ENABLED; the next scheduled run
will leave the Finsance checkout untouched.
