import click
from setfit import SetFitModel
import time

@click.command()
@click.option(
    "--in",
    "-i",
    "in_dir",
    required=True,
    help="Model path to process",
    type=click.Path(exists=True, dir_okay=True, readable=True),
)
def process(in_dir):
    print("Loading CPU model from: " + in_dir)
    print(time.time())
    setfit_model = SetFitModel.from_pretrained(in_dir)
    print("Loaded CPU model")
    print(time.time())

    context = setfit_model(["You are such a fossil."])
    print(context.item())
    print(time.time())

    context = setfit_model(["Working in the fossil fuel industry."])
    print(context.item())
    print(time.time())


if __name__ == "__main__":
    process()
