echo "Installing pdm"
pip install pdm
pdm run python -m ensurepip
pdm config check_update False

echo "Installing dependencies using pdm"

pdm sync --prod
