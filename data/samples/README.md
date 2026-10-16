# Reproducible source sample

`claimreviews.json` contains 12 unchanged ClaimReview objects selected from the official Google Data Commons / Fact Check Markup Tool feed downloaded on October 18, 2026 (IST). It contains structured markup only. See `manifest.json` for the original feed SHA-256, source URL, record indices, publisher attribution and licensing notes.

`annotations.json` is separate application data: five narrative frames, four topics and two technology entities across the 12 claims. Each annotation discloses **Codex AI-assisted text inspection; human review pending**. These classifications are inferences and are not publisher-supplied metadata. Entity evidence spans must occur in the source claim text.

The sample includes source records from FactCheck.org, PolitiFact, FACTLY, BBC Reality Check, Vera Files, Deutsche Welle, Logically Facts, PesaCheck and Fact Crescendo Sri Lanka. Some dates are absent in the original markup and remain absent.

`scripts/build_sample.py` records the exact selected variant IDs. To reconstruct this sample from the downloaded feed snapshot, first run the 250-record preparation command in the root README, then:

```powershell
python scripts/build_sample.py data/processed/claims.jsonl
```

The current feed may change, so later downloads may not contain all selected records. The included sample is the stable validation input. Synthetic test records are restricted to `tests/` and use `.example` URLs.
