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
    print("Loading GPU model from: " + in_dir)
    setfit_model = SetFitModel.from_pretrained(in_dir)

    print("Converting from GPU to CPU")
    setfit_model.to("cpu")

    out_dir = os.getcwd() + "/models/context_aware_model/" + language
    print("Writing CPU enabled model to: " + out_dir)

    setfit_model.save_pretrained(out_dir)


if __name__ == "__main__":
    process()
