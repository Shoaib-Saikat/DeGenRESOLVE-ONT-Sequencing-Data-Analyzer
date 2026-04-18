# DegenResolve - ONT Sequencing Data Analyzer

[![Release](https://img.shields.io/badge/Release-v1.0.0-blue)](https://github.com/Shoaib-Saikat/DeGenRESOLVE-ONT-Sequencing-Data-Analyzer/releases/tag/degenresolve)

## 🚀 Latest Release (v1.0.0 – Offline Bundle)

**DegenResolve ONT Sequencing Data Analyzer**  
📦 Version: v1.0.0 – Offline Installer Bundle  

🔗 Release Page:  
https://github.com/Shoaib-Saikat/DeGenRESOLVE-ONT-Sequencing-Data-Analyzer/releases/tag/degenresolve  

---

A fully self-contained offline installer is available for systems without internet access.

---

## 📦 Bundle Information

- **Archive**: `degenresolve_offline_bundle_1.0.0.tar.gz`
- **Size**: ~1.2 GB  
- **Includes**:
  - Pre-configured Conda environment
  - All Python dependencies
  - Required bioinformatics tools (samtools, bcftools, minimap2, porechop, etc.)
  - Fully integrated pipeline + GUI

---

### ⚙️ Installation (Offline)

### 1. Transfer the bundle
Download and copy the archive to the target machine (through USB, SCP, etc.)

### 2. Extract
```bash
tar -xzf degenresolve_offline_bundle_1.0.0.tar.gz
````

### 3. Run installer

```bash
bash degenresolve_bundle/install.sh
```

---

## ✅ Post-Installation Summary

After installation, you should see output similar to:

```
⚠ Installed with 1 warning(s) — see above.

Application : /home//degenresolve
Launcher    : /home/user/degenresolve/run_degenresolve.sh
Conda env   : /home/user/miniconda3/envs/degenresolve
Verified    : 14 passed, 1 warnings
```

---

## ▶️ Run Application

```bash
bash /home/user/degenresolve/run_degenresolve.sh
```

### Reload environment (if needed)

```bash
source ~/.bashrc
```

---

## 🧹 Uninstall

```bash
bash /home/user/APP/degenresolve_bundle/uninstall.sh
```

---

## ✨ Features

* Modular architecture (GUI + pipeline separation)
* Automatic checkpoint/resume system 🔄
* Real-time progress tracking
* Dynamic configuration support
* Comprehensive logging system
* Cross-platform Linux/WSL support

---

## 📂 Project Structure

```
DegenResolve/
├── src/degenresolve/
│   ├── gui/
│   ├── core/
│   ├── pipeline/
│   ├── utils/
│   └── scripts/
├── tests/
├── docs/
├── requirements.txt
├── setup.py
└── degenresolve.py
```

---

## 📥 Input Format

```
your_data_directory/
├── fastq_pass/
│   ├── barcode01/
│   └── barcode02/
└── reference/
    └── reference.fasta
```

---

## 📤 Output Structure

```
results/
├── step_1_merged/
├── step_2_trimmed/
├── step_3_mapped/
├── step_4_processed/
├── step_5_consensus/
├── step_6_edited/
├── quality_reports/
└── final_outputs/
```

---

## 🔄 Checkpoint System

The pipeline automatically resumes from the last completed step:

* Detects existing outputs
* Skips completed steps
* Prevents recomputation
* Handles interruptions safely

---

## 🧪 Development & Testing

```bash
python -m pytest tests/
```

---

## 🧬 Dependencies

* Python ≥ 3.8
* PyQt5
* BioPython
* pysam

### System tools

* samtools
* bcftools
* minimap2
* porechop

---

## 👤 Author

**Shoaib Saikat**
Research Intern, One Health Laboratory
ICDDRB, Bangladesh
MS in Biochemistry and Biotechnology, University of Barishal

---

## 📜 License

This project is developed for research purposes at icddr,b.

```
