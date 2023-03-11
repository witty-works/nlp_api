echo "Installing pdm"
pip install pdm
pdm config install.cache True
pdm config cache_dir $HOME/.pdm

pdm run python -m ensurepip