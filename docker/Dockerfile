FROM ubuntu:25.10 as base

ARG USER_ID=999
ARG GROUP_ID=1099
ARG USER_NAME=appuser
ARG GROUP_NAME=appgroup
ARG DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1


# RUN apt-get update && \
#     apt-get upgrade -y && \
#     apt-get install -y gnupg2 lsb-release ca-certificates wget && \
#     rm -rf /var/lib/apt/lists/*

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y gnupg2 lsb-release ca-certificates wget \
                       libpam-modules libpam-modules-bin libpam-runtime libpam0g && \
    rm -rf /var/lib/apt/lists/*
    
RUN sed -i '/pam_namespace.so/d' /etc/pam.d/common-session* || true
RUN addgroup --gid $GROUP_ID $GROUP_NAME \
    && adduser --disabled-password --gecos '' --uid $USER_ID --gid $GROUP_ID --home /home/$USER_NAME $USER_NAME \
    && chown -R $USER_NAME:$GROUP_NAME /home/$USER_NAME /home/ubuntu

ENV PATH="/home/${USER_NAME}/miniconda3/bin:${PATH}"
ARG PATH="/home/${USER_NAME}/miniconda3/bin:${PATH}"

USER $USER_NAME
RUN cd /home/${USER_NAME} && \
    wget \
    https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh \
    && mkdir /home/${USER_NAME}/.conda \
    && bash Miniconda3-latest-Linux-x86_64.sh -b \
    && rm -f Miniconda3-latest-Linux-x86_64.sh

RUN conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main && \
    conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r && \
    conda update -n base -y conda

COPY --chown=$USER_NAME:$GROUP_NAME . /home/ubuntu/codebase/

RUN cd /home/ubuntu/codebase/ &&\
    python -m ensurepip --upgrade &&\
    python -m pip install --upgrade setuptools &&\
    python -m pip install .

USER root
RUN apt-get purge -y wget && apt-get autoremove -y
RUN find /home/appuser/miniconda3/pkgs/ -wholename '*test/test*.py' -delete
WORKDIR /home/ubuntu/codebase/
USER $USER_NAME
