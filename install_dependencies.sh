echo "Installing pdm"
pip install pdm
pdm run python -m ensurepip
pdm config check_update False

echo "Installing dependencies using pdm"

if [ -z "${MODELS##*"fr_core_news_sm"*}" ]; then
    echo "Installing French fr_core_news_sm model"
    pdm add "fr_core_news_sm @ https://github.com/explosion/spacy-models/releases/download/fr_core_news_sm-3.7.0/fr_core_news_sm-3.7.0-py3-none-any.whl"
elif [ -z "${MODELS##*"fr_core_news_lg"*}" ]; then
    echo "Installing French fr_core_news_lg model"
    pdm add "fr_core_news_lg @ https://github.com/explosion/spacy-models/releases/download/fr_core_news_lg-3.7.0/fr_core_news_lg-3.7.0-py3-none-any.whl"
else
    pdm sync --prod
fi
