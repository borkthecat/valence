# WamboSec Prompt Injection Test Fixture

`wambosec-test.jsonl` is a deterministic field projection of the 577-record test split from `wambosec/prompt-injections` at revision `071ee17a60112b7f9f808398156b430aadfaf1d2`.

Source: https://huggingface.co/datasets/wambosec/prompt-injections

The dataset card declares the dataset under the MIT License. Copyright remains with its original authors. The fixture is included for reproducible security evaluation and retains only `prompt`, `label`, and non-null `category` values, renamed to the Valence benchmark schema. See `THIRD_PARTY_NOTICES.md` for the license terms.
