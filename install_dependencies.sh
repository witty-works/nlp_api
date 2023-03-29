echo "Installing pdm"
pip install pdm
pdm config check_update false
pdm run python -m ensurepip

echo "Installing dependencies using pdm"
pdm sync --prod
