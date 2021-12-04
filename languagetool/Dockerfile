FROM erikvl87/languagetool:5.5

# Become root user for file copying etc
USER root

# this should be added when using fasttext
#RUN apk add --update make
#RUN apk add --update git
#RUN apk add --update clang
#RUN apk add --update py3-numpy
#RUN apk add --update py3-scipy
#RUN apk add build-base
#RUN git clone https://github.com/facebookresearch/fastText.git
#WORKDIR fastText
#RUN make
#WORKDIR ..
#RUN l

# Add server properties, when we use fasttext change to previous command 
#COPY --chown=languagetool server.properties /LanguageTool
COPY --chown=languagetool server.properties /LanguageTool

#Add fasttext model
#lid.175.bin use a lot 126MB space, disable it when we will be using Docker images for production service.
#RUN wget https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.175.bin 

# Add our own entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# setup sshd for ssh access in app services
COPY ssh_setup.sh /tmp/sshd_setup.sh
RUN apk add --no-cache --update openssh-server su-exec \
  && bash /tmp/sshd_setup.sh \
  && rm -f /tmp/sshd_setup.sh \
  && echo "root:Docker!" | chpasswd
COPY sshd_config /etc/ssh/sshd_config

ENV PORT 8000
EXPOSE 8000 2222

# the percentage of heap size to use for languagetool
ENV HEAP_PERCENTAGE 80 

CMD [ "bash", "/entrypoint.sh" ]
