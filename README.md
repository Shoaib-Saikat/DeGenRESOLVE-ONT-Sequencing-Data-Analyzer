# DegenResolve - ONT Sequencing Data Analyzer

A modular, comprehensive application for processing ONT raw FASTQ files and generating refined consensus FASTA sequences.

## Features

- **Modular Architecture**: Clean separation of GUI, pipeline, and utility components
- **Checkpoint System**: Automatically detects completed steps and resumes from interruptions 🔄
- **Dynamic Configuration**: Flexible parameter adjustment for analysis
- **Real-time Progress Tracking**: Live updates during processing
- **Comprehensive Logging**: Detailed logs and result management
- **Cross-platform Support**: Works on Linux and WSL environments

## Quick Start

### GUI Application
```bash
# Simple launch
python3 degenresolve.py

# Or use the quick launcher
bash quick_launch.sh
```

### Package Installation
```bash
# Install in development mode
pip install -e .

# Then run anywhere
degenresolve
```

## Project Structure

```
DegenResolve/
├── src/degenresolve/           # Main package source
│   ├── gui/                    # GUI components
│   │   ├── main_window.py      # Main application window
│   │   ├── results_viewer.py   # Results display widget
│   │   └── styles.py           # UI themes and styling
│   ├── core/                   # Core functionality
│   │   ├── config.py           # Configuration management
│   │   ├── validator.py        # Input validation
│   │   └── signals.py          # Qt signals
│   ├── pipeline/               # Pipeline processing
│   │   ├── processor.py        # Main pipeline coordinator
│   │   ├── worker.py           # Background worker
│   │   └── consensus_editor.py # Consensus sequence editing
│   ├── utils/                  # Utility functions
│   │   ├── logging.py          # Logging utilities
│   │   └── file_utils.py       # File management
│   └── scripts/                # Shell scripts
│       ├── main_with_config.sh # Main pipeline script
│       └── *.sh                # Other pipeline scripts
├── tests/                      # Test suite
├── docs/                       # Documentation
├── requirements.txt            # Python dependencies
├── setup.py                   # Package setup
└── degenresolve.py            # Main launcher
```

## Dependencies

- Python 3.8+
- PyQt5 (GUI framework)
- BioPython (sequence analysis)
- pysam (BAM file handling)
- System tools: samtools, bcftools, minimap2, porechop

## Usage

### Expected Input Structure
```
your_data_directory/
├── fastq_pass/
│   ├── barcode01/
│   │   └── *.fastq.gz
│   └── barcode02/
│       └── *.fastq.gz
└── reference/
    └── reference.fasta
```

### Configuration

The application supports both GUI-based configuration and JSON config files. Configuration includes:

- Coverage thresholds
- Degeneracy resolution parameters
- Ploidy settings
- Variant calling parameters
- Quality control options

### Output

Results are organized in a step-based structure for easy navigation:

```
results/
├── step_1_merged/           # barcode*_merged.fastq
├── step_2_trimmed/          # barcode*_trimmed.fastq
├── step_3_mapped/           # barcode*.sam
├── step_4_processed/        # barcode*/ (BAM, coverage, variants)
├── step_5_consensus/        # barcode*_consensus.fasta
│   └── fastq/               # barcode*_consensus.fastq
├── step_6_edited/           # barcode*_consensus_edited.fasta
├── quality_reports/         # barcode*/ (QC reports)
└── final_outputs/           # barcode*_consensus_edited.fasta
```

**Key locations:**
- `results/final_outputs/`: Main consensus results
- `log/`: Processing logs and diagnostics

See `ORGANIZED_RESULTS_STRUCTURE.md` for detailed explanation.

## 🔄 Checkpoint System

The pipeline includes an intelligent checkpoint system that automatically detects completed steps:

### **Automatic Resume**
```bash
# If pipeline is interrupted, simply restart - it will resume automatically
python3 degenresolve.py  # GUI mode
# OR
bash src/degenresolve/scripts/main_with_config.sh pipeline_config.json  # CLI mode
```

### **Step Detection**
The system checks for completion of each step:
- **Step 1**: `results/step_1_merged/barcode*_merged.fastq`
- **Step 2**: `results/step_2_trimmed/barcode*_trimmed.fastq` 
- **Step 3**: `results/step_3_mapped/barcode*.sam`
- **Step 4**: `results/step_4_processed/barcode*/barcode*.bam` + index
- **Step 5**: `results/step_5_consensus/barcode*_consensus.fasta` + FASTQ
- **Step 6**: `results/step_6_edited/barcode*_consensus_edited.fasta`

### **Benefits**
✅ **Time Saving**: Skip completed computations  
✅ **Fault Tolerance**: Automatic recovery from interruptions  
✅ **Resource Efficiency**: Only process what's needed  
✅ **Flexible Workflow**: Resume from any completed step

## Development

### Running Tests
```bash
python -m pytest tests/
```

### Code Style
The project follows PEP 8 conventions with modular design principles.

## Author

**Shoaib Saikat**
- Research Intern, One Health Laboratory, Infectious Diseases Division
- International Centre for Diarrhoeal Disease Research, Bangladesh (icddr,b)
- MS Student, Department of Biochemistry and Biotechnology
- University of Barishal, Bangladesh

## License

This project is developed for research purposes at icddr,b.
