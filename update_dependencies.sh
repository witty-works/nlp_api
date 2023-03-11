echo "Installing pdm dependecies"
pdm sync --prod

echo "Saving to build cache"
rsync -ar $HOME/.venv/ $PLATFORM_CACHE_DIR/.venv
rsync -ar $HOME/.global/ $PLATFORM_CACHE_DIR/.global
rsync -ar $HOME/.pdm/ $PLATFORM_CACHE_DIR/.pdm
echo "Done saving to build cache"