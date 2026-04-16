# DeGenRESOLVE Offline Installer

This directory contains everything needed to build a self-extracting offline installer for DeGenRESOLVE.

## Layout

```text
DeGenRESOLVE-installer/
├── build_installer.sh
├── install.sh
├── README_installer.md
└── payload/
    ├── app/
    ├── env/
    │   └── pyvcf_env.tar.gz
    └── bin/
```

## 1) Prepare payload/app

From the repository root:

```bash
mkdir -p DeGenRESOLVE-installer/payload/app
rsync -a --delete --exclude '.git' ./ DeGenRESOLVE-installer/payload/app/
```

> Tip: remove installer artifacts from the copied app directory if you do not want recursive content.

## 2) Pack conda environment

```bash
pip install conda-pack
conda activate pyvcf_env
conda-pack -n pyvcf_env -o pyvcf_env.tar.gz
mv pyvcf_env.tar.gz DeGenRESOLVE-installer/payload/env/
```

## 3) (Optional) Bundle external binaries

Copy any required system binaries into `payload/bin` (for example `samtools`, `bcftools`, `minimap2`).

## 4) Build installer

```bash
cd DeGenRESOLVE-installer
chmod +x install.sh build_installer.sh
./build_installer.sh
```

Result:

```text
DeGenRESOLVE-installer/DeGenRESOLVE_installer.run
```

## 5) End user installation

```bash
bash DeGenRESOLVE_installer.run
```

The installer writes to `$HOME/DeGenRESOLVE` by default and creates a shortcut:

```text
~/.local/bin/degenresolve
```

## Notes and pitfalls

- Ensure scripts in your app use relative paths (for example with `$(dirname "$0")`) and avoid hardcoded absolute paths.
- Always test relocation after packing the conda environment:

```bash
~/DeGenRESOLVE/run_DeGenRESOLVE.sh --help
```

- Installer size of 1-3 GB is normal for bioinformatics workloads.
