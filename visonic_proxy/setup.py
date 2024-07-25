import codecs
import os
import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()


def read(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with codecs.open(os.path.join(here, rel_path), "r") as fp:
        return fp.read()


def get_version(rel_path):
    for line in read(rel_path).splitlines():
        if line.startswith("__VERSION__"):
            delim = '"' if '"' in line else "'"
            return line.split(delim)[1]
    else:
        raise RuntimeError("Unable to find version string.")


setuptools.setup(
    name="pyvisonicalarm",
    version=get_version("pyvisonicalarm/__init__.py"),
    author="Mark Parker",
    author_email="msparker@sky.com",
    description="A simple library for the Visonic Alarm API written in Python 3",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/msp1974/pyvisonicalarm",
    packages=setuptools.find_packages(),
    install_requires=["requests"],
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.12",
)
