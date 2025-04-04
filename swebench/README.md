## SWE-bench's evaluation harness
For each task instance of the SWE-bench dataset, given an issue (`problem_statement`) + codebase (`repo` + `base_commit`), eval_swebench.py attempts to apply a specific prediction to the repo and run an evaluation of the tests.

Each prediction must be formatted as follows:
```json
{
    "instance_id": "<Unique task instance ID>",
    "model_patch": "<.patch file content string>",
    "model_name_or_path": "<Model name here (i.e. SWE-Llama-13b)>",
}
```

Store multiple predictions in a `.json` file formatted as `[<prediction 1>, <prediction 2>,... <prediction n>]`. It is not necessary to generate predictions for every task instance.

If you'd like examples, the [swe-bench/experiments](https://github.com/swe-bench/experiments) GitHub repository contains many examples of well formed patches.

## Running Evaluations
You can run evaluations entirely on the cloud using [Morph Cloud](https://cloud.morph.so/docs/developers) to avoid local setup and resource constraints:

```bash
uv run eval_swebench.py \
  --dataset_name <dataset-name> \
  --predictions_path <path-to-predictions.json> \
  --max_workers <max-number-of-workers> \
  --run_id <unique-run-identifier> \
  --split <dataset-split> \
  --instance_ids <space-separated-instance-ids> \
  --report_dir <report-directory-path> \
  --rewrite_reports <true|false>
```

### Command-line Arguments

| Argument | Type | Required | Default | Description | Example |
|----------|------|----------|---------|-------------|---------|
| `--dataset_name` | string | No | `princeton-nlp/SWE-bench_Lite` | Name of the SWE-bench dataset to use | `princeton-nlp/SWE-bench_Lite` |
| `--predictions_path` | file path | Yes | - | Path to the JSON or JSONL file containing predictions | `./all_preds.jsonl` |
| `--max_workers` | integer | No | `4` | Maximum number of parallel workers to use | `4` |
| `--run_id` | string | Yes | - | Unique identifier for this evaluation run | `run_20230901` |
| `--split` | string | No | `test` | Dataset split to evaluate on (dev/test) | `test` |
| `--instance_ids` | list of strings | No | - | Optional: specific space-separated instance IDs to evaluate (will evaluate all instances with predictions if left empty) | `astropy__astropy-7166 django__django-10880 pydata_xarray-6599` |
| `--report_dir` | directory path | No | `logs` | Path where evaluation reports will be saved | `./reports` |
| `--rewrite_reports` | boolean | No | `False` | Whether to overwrite existing reports | `true` |

You can run evaluation for the following (`dataset_name`, `split`)
* `princeton-nlp/SWE-bench_Lite`, `test` (300 task instances)
* `princeton-nlp/SWE-bench_Verified`, `test` (500)
* `princeton-nlp/SWE-bench`, `dev` (225)
* `princeton-nlp/SWE-bench`, `test` (2294)
* `princeton-nlp/SWE-bench_Multimodal`, `dev` (102)

You *cannot* run evaluation on the `test` split of `princeton-nlp/SWE-bench_Multimodal` using this repository (517 instances).
To encourage less intentional climbing of the leaderboard, we have intentionally made specifications for evaluating the test split private.
Use [sb-cli](https://github.com/swe-bench/sb-cli/) for SWE-bench Multimodal evaluation.
