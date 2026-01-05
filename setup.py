#!/usr/bin/env python3
"""
Setup script for Monitor Control
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text() if readme_path.exists() else ""

setup(
    name="monitor-control",
    version="1.0.0",
    author="Pink-o",
    description="DDC/CI based monitor control for Linux with automatic profile switching",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Pink-o/monitor-control",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "": ["*.yaml", "*.yaml.example"],
        "assets": ["*.png", "*.ico"],
        "patches": ["*.patch", "*.sh"],
    },
    python_requires=">=3.8",
    install_requires=[
        "customtkinter>=5.0.0",
        "PyYAML>=6.0",
        "Pillow>=9.0.0",
        "numpy>=1.20.0",
    ],
    extras_require={
        "x11": [
            "python-xlib>=0.33",
            "mss>=6.0.0",
        ],
        "full": [
            "python-xlib>=0.33",
            "mss>=6.0.0",
            "dbus-python>=1.3.2",
        ],
    },
    entry_points={
        "console_scripts": [
            "monitor-control=main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Environment :: X11 Applications :: GTK",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Desktop Environment",
        "Topic :: System :: Hardware",
    ],
)


