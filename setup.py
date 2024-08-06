"""Visonic Proxy setup."""

import codecs
import os

import setuptools

with open("README.md", encoding="utf-8") as fh:
    long_description = fh.read()


def read(rel_path):
    """Read file."""
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, rel_path), "r") as fp:
        return fp.read()


def get_version(rel_path):
    """Get version from init."""
    for line in read(rel_path).splitlines():
        if line.startswith("__VERSION__"):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    raise RuntimeError("Unable to find version string.")


setuptools.setup(
    name="visonicproxy",
    version=get_version("visonic_proxy/__init__.py"),
    author="Mark Parker",
    author_email="msparker@sky.com",
    description="A Proxy Manager for Visonic PowerLink 3 written in Python 3",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/msp1974/visonic_proxy",
    packages=setuptools.find_packages(),
    install_requires=["requests"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.12",
)
