# Fastly Debug CLI

## Introduction
This tool contains all the code necessary to produce the output for Fastly 
Support folks to begin debugging connection issues from command line interfaces 
without requiring Javascript.

Where possible it is best to use the fully supported 
[GUI](https://www.fastly-debug.com/) version available.

## Installation

### Prerequisites
To use this you will need Python 3.x and PIP installed. All commands noted here assume the
system is configured to use Python and PIP3 as default. If your system uses another version,
or executable name substitute this instead.

### Installing

Download the code and extract it to a suitable location on the machine to run the tool on.

### Configuration
To install the required modules run `pip install -r requirements.txt`.

## Usage
To generate the hash data to screen for Fastly to review run `fastly_debug`
without any arguments.

To generate the hash and output to a file: `fastly_debug -o <filename>`.

To view the help run `fastly_debug -h`