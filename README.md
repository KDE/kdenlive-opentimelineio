<!--
    SPDX-License-Identifier: CC-BY-SA-4.0
    SPDX-FileCopyrightText: 2022 Julius Künzel <jk.kdedev@smartlab.uber.space>
-->


# OpenTimelineIO Kdenlive Adapter

This repository contains the OpenTimelineIO adapter for the Kdenlive file format (`*.kdenlive`). It is distributed under the MIT License.

# HELP NEEDED!

Please note that this adapter is behind the quickly evolving features of Kdenlive and hence might be unstable. We are looking for help to maintain the OpenTimelineIO support for Kdenlive. The long term goal is to add proper support to the C++ source code of Kdenlive to replace this Python adapter. If you like to help, we are happy to hear from you!

## What is Kdenlive?

[Kdenlive](https://kdenlive.org) is a Free and Open Source video editing application, based on MLT Framework and KDE Frameworks.

In case you are looking for the source code of Kdenlive, it is here: https://invent.kde.org/multimedia/kdenlive

## What is OpenTimelineIO?

[OpenTimelineIO](https://opentimeline.io) is an interchange format and API for editorial cut information. OTIO contains information about the order and length of cuts and references to external media. It is not however, a container format for media.

For integration with applications, the [core OTIO library](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) is implemented in C++ the project also supports an official python binding. The python binding includes a plugin system which supports a number of different types of plugins, most notably adapters (like this one).

### Adapter Plugins

To provide interoperability with other file formats or applications lacking a native integration, the opentimelineio community has built a number of python adapter plugins. Beside Kdenlive this includes Final Cut Pro XML, AAF, CMX 3600 EDL, and more.

For more information about this, including supported formats, see: https://opentimelineio.readthedocs.io/en/latest/tutorials/adapters.html

A list of tools and projects using OpenTimelineIO can be found [here](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/wiki/Tools-and-Projects-Using-OpenTimelineIO).

## Installing

As a user you can usually just install the adapter through the Kdenlive user interface or directly from pypi.org with this command

```bash
python -m pip install otio-kdenlive-adapter
```

## Development

The OpenTimelineIO documentation can be found here: https://opentimelineio.readthedocs.io

### Testing the plugin during development
```bash
# In the root folder of the repo
pip install -e .

# Test an adapter for instance
otioconvert -i some_timeline.otio -o some_timeline.kdenlive
```

The OpenTimelineIO documentation can be found here: https://opentimelineio.readthedocs.io

### Unit tests

It's always a good idea to write unit tests for you code.
Please provide tests that run against supported versions of python and OpenTimelineIO.

To run the unit tests do
```bash
# In the root folder of the repo
pytest
```

Before pushing changes you should also run the linter
```bash
flake8 --show-source
```
