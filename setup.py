# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2022 The KDE Community

import io
import setuptools

with io.open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()


setuptools.setup(
    name="otio-kdenlive-adapter",
    author="Kdenlive Community",
    author_email="kdenlive@kde.org",
    version="0.0.1",
    description="Short description of your plugin",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://invent.kde.org/jlskuz/otio-kdenlive-adapter",
    packages=setuptools.find_packages(),
    entry_points={
        "opentimelineio.plugins": "otio_kdenlive_adapter = otio_kdenlive_adapter"
    },
    package_data={
        "otio_kdenlive_adapter": [
            "plugin_manifest.json",
        ],
    },
    install_requires=[
        "OpenTimelineIO >= 0.14.0"
    ],
    extras_require={
        "dev": [
            "flake8",
            "pytest",
            "pytest-cov",
            "twine"
        ]
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Multimedia :: Video",
        "Topic :: Multimedia :: Video :: Display",
        "Topic :: Multimedia :: Video :: Non-Linear Editor",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Operating System :: OS Independent",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English"
    ]
)
