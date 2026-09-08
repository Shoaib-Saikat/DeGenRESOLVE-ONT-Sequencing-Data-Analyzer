"""
Setup script for DegenResolve

This script installs the DegenResolve ONT Sequencing Data Analyzer package.
"""

from setuptools import setup, find_packages
import os

# Read the requirements file
def read_requirements():
    requirements_path = os.path.join(os.path.dirname(__file__), 'requirements.txt')
    with open(requirements_path, 'r') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

# Read the README file for long description
def read_readme():
    readme_path = os.path.join(os.path.dirname(__file__), 'README.md')
    if os.path.exists(readme_path):
        with open(readme_path, 'r', encoding='utf-8') as f:
            return f.read()
    return "ONT Sequencing Data Analyzer with PyQt5 GUI"

setup(
    name="degenresolve",
    version="1.0.0",
    author="Shoaib Saikat",
    author_email="saikatshoaib@gmail.com",
    description="ONT Sequencing Data Analyzer with PyQt5 GUI",
    long_description=read_readme(),
    long_description_content_type="text/markdown",
    url="https://github.com/Shoaib-Saikat/DeGenRESOLVE-ONT-Sequencing-Data-Analyzer",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Bio-Informatics",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        # 3.8 and 3.9 are NOT supported: consensus_editor.py uses PEP 604 `str | None`
        # annotations, which are evaluated at class-definition time and raise
        # TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'
        # on any interpreter older than 3.10. Advertising 3.8 meant `pip install` succeeded
        # and the tool then failed at import with an error that points nowhere useful.
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: POSIX :: Linux",
    ],
    python_requires=">=3.10",
    install_requires=read_requirements(),
    include_package_data=True,
    package_data={
        "degenresolve": [
            "scripts/*.sh",
            "scripts/*.py",
            "app_data/*",
        ],
    },
    # The shell scripts are the pipeline. Without this a wheel installs the Python package
    # and silently omits main_with_config.sh, so `degenresolve` starts and then fails at the
    # first run with a missing-file error.
    zip_safe=False,
    entry_points={
        "console_scripts": [
            "degenresolve=degenresolve.main:main",
            "degenresolve-consensus=degenresolve.pipeline.consensus_editor:main",
        ],
    },
)
