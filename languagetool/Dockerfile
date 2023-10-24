FROM erikvl87/languagetool:6.2

# https://github.com/Erikvl87/docker-languagetool#improving-the-spell-checker
USER languagetool

COPY en_ignore.txt en_ignore.txt
RUN  (echo; cat en_ignore.txt) >> org/languagetool/resource/en/hunspell/ignore.txt

COPY de_ignore.txt de_ignore.txt
RUN  (echo; cat de_ignore.txt) >> org/languagetool/resource/de/hunspell/ignore.txt

WORKDIR /LanguageTool

COPY --chown=languagetool config.properties config.properties
