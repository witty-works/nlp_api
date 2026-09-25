"""Convert a downloaded SetFit model (possibly GPU-trained) to a CPU-only
version stored under `models/context_aware_model/<lang>`.

Why this is needed
------------------
The local context checker loads SetFit models and places their underlying
`model_body` modules into shared memory (`share_memory()`) so multiple worker
processes (e.g. uvicorn / gunicorn) can perform inference without duplicating
model weights. GPU tensors cannot be shared this way across processes without
specialized coordination. Converting the model to run on CPU ensures the
weights are placed in regular host memory, enabling efficient multi-process
forking and reducing per-process RAM usage.

Usage
-----
Download the model first (example Azure ML command omitted here – see README),
then run:

        pdm run python -m bin.convert_to_cpu -i path/to/downloaded/model -l en

For German or French replace `-l en` with `-l de` or `-l fr`.

Inputs
------
--in / -i : Path to the source model directory that contains the original
                         SetFit artifacts (config.json, pytorch_model.bin, etc.)
--lang / -l: Language code used to determine output folder.

Outputs
-------
Writes a CPU-converted SetFit model to:
        models/context_aware_model/<lang>

Edge cases / notes
------------------
* Existing output directory contents will be overwritten.
* Ensure the destination path is included in deployments (e.g. rsync step).
* The script does not validate language codes beyond using them as a path
    suffix.
* If the source model is already CPU-based, conversion simply saves a copy.
"""

import os
import click
from setfit import SetFitModel


@click.command()
@click.option(
    "--in",
    "-i",
    "in_dir",
    required=True,
    help="Model path to process",
    type=click.Path(exists=True, dir_okay=True, readable=True),
)
@click.option(
    "--lang",
    "-l",
    "language",
    required=True,
    help="Model language to determine output dir",
)
def process(in_dir, language):
    """Load a SetFit model from `in_dir`, move it to CPU and persist it.

    Parameters
    ----------
    in_dir : str
        Path to the downloaded SetFit model directory.
    language : str
        Language identifier used for naming the output folder.
    """
    print(f"Loading model from: {in_dir}")
    setfit_model = SetFitModel.from_pretrained(in_dir)

    print("Converting model to CPU (if not already)")
    setfit_model.to("cpu")

    out_dir = os.path.join(os.getcwd(), "models", "context_aware_model", language)
    print(f"Writing CPU model to: {out_dir}")

    # Create parent directories if they don't exist
    os.makedirs(out_dir, exist_ok=True)
    setfit_model.save_pretrained(out_dir)
    print("Done.")


if __name__ == "__main__":
    process()
