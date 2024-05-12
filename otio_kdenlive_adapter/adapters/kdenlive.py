# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2019-2022 Vincent Pinon <vpinon@kde.org>
# SPDX-FileCopyrightText: 2021 "splidje"
# SPDX-FileCopyrightText: 2022 Julius Künzel <jk.kdedev@smartlab.uber.space>

"""Kdenlive (MLT XML) Adapter."""
import json
import os
import re
import sys
from enum import Enum
from xml.dom import minidom
from xml.etree import ElementTree as ET

import opentimelineio as otio

try:
    from urllib.parse import unquote, urlparse
except ImportError:
    # Python 2
    from urllib import unquote

    from urlparse import urlparse


marker_types = {
    0: (otio.schema.MarkerColor.PURPLE, '#9b59b6'),
    1: (otio.schema.MarkerColor.CYAN, '#3daee9'),
    2: (otio.schema.MarkerColor.BLUE, '#1abc9c'),
    3: (otio.schema.MarkerColor.GREEN, '#1cdc9a'),
    4: (otio.schema.MarkerColor.YELLOW, '#c9ce3b'),
    5: (otio.schema.MarkerColor.ORANGE, '#fdbc4b'),
    6: (otio.schema.MarkerColor.RED, '#f39c1f'),
    7: (otio.schema.MarkerColor.PINK, '#f47750'),
    8: (otio.schema.MarkerColor.MAGENTA, '#da4453')
}

marker_categories = {}

# From definitions.h in Kdenlive source code


class ProducerType(Enum):
    Unknown = 0,
    Audio = 1
    Video = 2
    AV = 3
    Color = 4
    Image = 5
    Text = 6
    SlideShow = 7
    Virtual = 8
    Playlist = 9
    WebVfx = 10
    TextTemplate = 11
    QText = 12
    Composition = 13
    Track = 14
    Qml = 15
    Animation = 16
    Timeline = 17


def read_property(element, name):
    """Decode an MLT item property
    which value is contained in a "property" XML element
    with matching "name" attribute"""
    return element.findtext("property[@name='{}']".format(name), '')


def time(clock, rate):
    """Decode an MLT time
    which is either a frame count or a timecode string
    after format hours:minutes:seconds.floatpart"""
    hms = [float(x) for x in clock.replace(',', '.').split(':')]
    if len(hms) > 1:
        smh = list(reversed(hms))
        hours = smh[2] if len(hms) > 2 else 0
        mins = smh[1]
        secs = smh[0]
        # unpick the same rounding/flooring from the clock function
        # (N.B.: code from the clock function mimicks what
        # I've seen from the mlt source code.
        # It's technically wrong. Or at least, I believe
        # it's written assuming an integer frame rate)
        f = (
            round(secs * rate) +
            int(mins * 60 * rate) +
            int(hours * 3600 * rate)
        )
    else:
        f = hms[0]
    return otio.opentime.RationalTime(f, rate)


def read_keyframes(kfstring, rate):
    """Decode MLT keyframes
    which are in a semicolon (;) separated list of time/value pair
    separated by = (linear interp) or ~= (spline) or |= (step)
    becomes a dict with RationalTime keys"""
    return dict((str(time(t, rate).value), v)
                for (t, v) in re.findall('([^|~=;]*)[|~]?=([^;]*)', kfstring))


def read_markers(markers_array, json_string, rate):
    """Convert Kdenlive's marker structure (JSON string) to otio markers"""
    if json_string:
        markers = json.loads(json_string)
        for json_marker in markers:
            time_range = otio.opentime.TimeRange(
                otio.opentime.RationalTime(json_marker["pos"], rate),
                otio.opentime.RationalTime(0, rate)
            )
            marker = otio.schema.Marker(
                name=json_marker["comment"],
                marked_range=time_range,
                color=marker_types[json_marker["type"]][0]
            )
            markers_array.append(marker)


def read_mix(mix, rate):
    value = read_property(mix, 'kdenlive:mixcut')
    if value == '':
        # missing mixcut property: this is a transition, but not a mix
        return None, None, None, None
    before_mix_cut = time(value, rate)

    mix_range = otio.opentime.TimeRange.range_from_start_end_time(
        start_time=time(mix.get('in'), rate),
        end_time_exclusive=(time(mix.get('out'), rate))
    )
    after_mix_cut = mix_range.duration - before_mix_cut
    reverse = bool(int(read_property(mix, 'reverse')))

    return mix_range, before_mix_cut, after_mix_cut, reverse


def item_from_xml(xml_item, rate, byid, bin_producer_name):
    """Create an otio item from xml"""
    if xml_item.tag == 'blank':
        # the item is a gap
        gap = otio.schema.Gap(
            duration=time(xml_item.get('length'), rate))
        return gap
    elif xml_item.tag == 'entry':
        # the item is a link to a producer
        producer = byid[xml_item.get('producer')]
        service = read_property(producer, 'mlt_service')
        available_range = otio.opentime.TimeRange.range_from_start_end_time(
            start_time=time(producer.get('in'), rate),
            end_time_exclusive=(
                time(producer.get('out'), rate) +
                otio.opentime.RationalTime(1, rate)
            ),
        )
        source_range = otio.opentime.TimeRange.range_from_start_end_time(
            start_time=time(xml_item.get('in'), rate),
            end_time_exclusive=(
                time(xml_item.get('out'), rate) +
                otio.opentime.RationalTime(1, rate)
            ),
        )
        # media reference clip
        reference = None
        if service in ['avformat', 'avformat-novalidate', 'qimage']:
            # producer is a file based clip
            reference = otio.schema.ExternalReference(
                target_url=read_property(
                    producer, 'kdenlive:originalurl') or
                read_property(producer, 'resource'),
                available_range=available_range)
        elif service == 'color':
            # producer is a color clip
            reference = otio.schema.GeneratorReference(
                generator_kind='SolidColor',
                parameters={'color': read_property(producer, 'resource')},
                available_range=available_range)
        elif (service == 'frei0r.test_pat_B' and
              read_property(producer, '0') == '4'):
            # producer is a smpt bar clip
            reference = otio.schema.GeneratorReference(
                generator_kind='SMPTEBars',
                available_range=available_range)
        clip = otio.schema.Clip(
            name=read_property(producer, 'kdenlive:clipname'),
            source_range=source_range,
            media_reference=reference or otio.schema.MissingReference())
        # process clip markers, they are only stored in the bin producer
        bin_producer = byid[bin_producer_name[read_property(producer, 'kdenlive:id')]]
        read_markers(clip.markers,
                     read_property(bin_producer, 'kdenlive:markers'), rate)
        # process effects
        for effect in xml_item.findall('filter'):
            kdenlive_id = read_property(effect, 'kdenlive_id')
            if kdenlive_id in ['fadein', 'fade_from_black',
                               'fadeout', 'fade_to_black']:
                clip.effects.append(otio.schema.Effect(
                    effect_name=kdenlive_id,
                    metadata={'duration':
                              time(effect.get('out'), rate) -
                              time(effect.get('in',
                                              producer.get('in')), rate)
                              }))
            elif kdenlive_id in ['volume', 'brightness']:
                clip.effects.append(otio.schema.Effect(
                    effect_name=kdenlive_id,
                    metadata={'keyframes': read_keyframes(
                        read_property(effect, 'level'), rate)}))
        return clip
    return None


def resize_item(item, delta, right):
    """Resize an item and keep its position (no ripple)
    by resizing the neighbors too"""
    item.source_range = otio.opentime.TimeRange(
        start_time=(item.source_range.start_time -
                    (delta if not right else otio.opentime.RationalTime(0))),
        duration=item.source_range.duration + delta
    )
    if right:
        after = item.parent().neighbors_of(item)[1]
        if after:
            after.source_range = otio.opentime.TimeRange(
                start_time=after.source_range.start_time,
                duration=after.source_range.duration - delta
            )
    else:
        before = item.parent().neighbors_of(item)[0]
        if before:
            before.source_range = otio.opentime.TimeRange(
                start_time=before.source_range.start_time,
                duration=before.source_range.duration - delta
            )


def get_maintracktor(mlt, byid, docversion):
    maintractor = mlt.find("tractor[@global_feed='1']")
    if maintractor is not None:
        return maintractor

    # global_feed is no longer set in newer kdenlive versions
    alltractors = mlt.findall("tractor")
    # the last tractor is the main tractor
    maintractor = alltractors[-1]
    if float(docversion) < float("1.1"):
        # for files without nested timelines
        # check all other tractors are used as tracks
        for tractor in alltractors[:-1]:
            query = "track[@producer='%s']" % tractor.attrib['id']
            if maintractor.find(query) is None:
                raise RuntimeError(
                    "Some tractors are neither the main tractor nor used as track")
        return maintractor
    else:
        # for project with nested timeline support (since 1.1)
        # the last tractor is only a wrap to the last opened tractor
        # which we consider to be the main tractor
        if int(read_property(maintractor, 'kdenlive:projectTractor')) != 1:
            return None
        pid = maintractor.find('track').get('producer')
        return byid[pid]


def read_from_string(input_str):
    """Read a Kdenlive project (MLT XML)
    Kdenlive uses a given MLT project layout, similar to Shotcut,
    combining a "main_bin" playlist to organize source media,
    and a "global_feed" tractor for timeline.
    Timeline tracks include virtual sub-track,
    used for same-track transitions"""
    mlt, byid = ET.XMLID(input_str)
    profile = mlt.find('profile')
    rate = (float(profile.get('frame_rate_num')) /
            float(profile.get('frame_rate_den', 1)))

    main_bin = mlt.find("playlist[@id='main_bin']")
    docversion = read_property(main_bin, "kdenlive:docproperties.version")
    bin_producer_name = {}
    for entry in main_bin.findall('entry'):
        producer = byid[entry.get('producer')]
        kdenlive_id = read_property(producer, 'kdenlive:id')
        bin_producer_name[kdenlive_id] = producer.get('id')

    timeline = otio.schema.Timeline(
        name=mlt.get('name', 'Kdenlive imported timeline'))

    maintractor = get_maintracktor(mlt, byid, docversion)

    if maintractor is None:
        raise RuntimeError("Can't find main tractor")

    for maintrack in maintractor.findall('track'):
        btid = 'black_track'
        if maintrack.get('producer') == btid:
            continue

        subtractor = byid[maintrack.get('producer')]

        if read_property(subtractor, 'kdenlive:playlistid') == btid:
            continue

        stack = otio.schema.Stack()

        subtracks = subtractor.findall('track')
        for sub in subtracks:
            mixTrack = otio.schema.Track()
            playlist = byid[sub.get('producer')]
            for xml_item in playlist.iter():
                item = item_from_xml(xml_item, rate, byid, bin_producer_name)
                if item:
                    mixTrack.append(item)
            if mixTrack.find_clips():
                stack.append(mixTrack)

        # process "mixes" (same-track-transitions)
        mixes = subtractor.findall('transition')

        # 1. step: flaten internal mix tracks to one track
        for mix in mixes:
            (mix_range, before_mix_cut,
             after_mix_cut, reverse) = read_mix(mix, rate)
            if mix_range is None:
                continue

            found_clip = stack[0].find_clips(search_range=mix_range)[0]
            resize_item(found_clip,
                        - (after_mix_cut if reverse else before_mix_cut),
                        not reverse)

            found_clip = stack[1].find_clips(search_range=mix_range)[0]
            resize_item(found_clip,
                        - (before_mix_cut if reverse else after_mix_cut),
                        reverse)

        track = otio.algorithms.flatten_stack(stack)

        # 2. step: build and insert transitions
        for mix in mixes:
            (mix_range, before_mix_cut,
             after_mix_cut, reverse) = read_mix(mix, rate)
            if mix_range is None:
                continue

            found_clip = track.find_clips(
                search_range=otio.opentime.TimeRange.range_from_start_end_time(
                    start_time=(time(mix.get('in'), rate) -
                                otio.opentime.RationalTime(
                                    1 if before_mix_cut.value == 0 else 1)),
                    end_time_exclusive=(time(mix.get('out'), rate))
                ))[0]
            index = track.index(found_clip)
            track.insert(index + 1, otio.schema.Transition(
                transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                in_offset=after_mix_cut,
                out_offset=before_mix_cut
            ))

        track.name = read_property(subtractor, 'kdenlive:track_name')
        if bool(read_property(subtractor, 'kdenlive:audio_track')):
            track.kind = otio.schema.TrackKind.Audio
        else:
            track.kind = otio.schema.TrackKind.Video
        timeline.tracks.append(track)

    # process "compositions" (transitions between clips in different tracks)
    for transition in maintractor.findall('transition'):
        kdenlive_id = read_property(transition, 'kdenlive_id')
        if kdenlive_id == 'wipe':
            b_track = int(read_property(transition, 'b_track'))
            timeline.tracks[b_track - 1].append(
                otio.schema.Transition(
                    transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                    in_offset=time(transition.get('in'), rate),
                    out_offset=time(transition.get('out'), rate)))

    # process timeline markers
    if float(docversion) < float("1.1"):
        read_markers(timeline.tracks.markers,
                     read_property(main_bin, "kdenlive:docproperties.guides"),
                     rate)
    else:
        read_markers(timeline.tracks.markers,
                     read_property(maintractor, "kdenlive:sequenceproperties.guides"),
                     rate)
    return timeline


def write_property(element, name, value):
    """Store an MLT property
    value contained in a "property" sub element
    with defined "name" attribute"""
    property = ET.SubElement(element, 'property', {'name': name})
    property.text = value


def clock(time):
    """Encode time to an MLT timecode string
    after format hours:minutes:seconds.floatpart"""
    frames = time.to_frames()
    hours = int(frames / (time.rate * 3600))
    frames -= int(hours * 3600 * time.rate)
    mins = int(frames / (time.rate * 60))
    frames -= int(mins * 60 * time.rate)
    secs = frames / time.rate
    return "%02d:%02d:%06.3f" % (hours, mins, secs)


def write_keyframes(kfdict):
    """Build a MLT keyframe string"""
    return ';'.join('{}={}'.format(t, v)
                    for t, v in kfdict.items())


def write_markers(markers):
    """Convert otio markers to Kdenlive's marker structure (JSON string)"""
    markers_array = []
    for marker in markers:
        try:
            marker_type = [
                key for key in marker_types.items() if key[1][0] == marker.color
            ][0][0]
        except Exception:
            marker_type = 0
        markers_array.append(
            {
                "pos": marker.marked_range.start_time.to_frames(),
                "comment": marker.name,
                "type": marker_type
            }
        )
        if marker_type not in marker_categories:
            # Since Kdenlive 22.12.0 there are no static build-in
            # categories anymore instead you can create as many
            # custom categories as you want.
            # Hence we need to create categories now.
            marker_categories[marker_type] = {
                "color": marker_types[marker_type][1],
                "comment": f"Category {len(marker_categories) + 1}",
                "index": marker_type
            }
    return json.dumps(markers_array)


def write_to_string(input_otio):
    """Write a timeline to Kdenlive project
    Re-creating the bin storing all used source clips
    and constructing the tracks"""
    if (not isinstance(input_otio, otio.schema.Timeline) and
            len(input_otio) > 1):
        print('WARNING: Only one timeline supported, using the first one.')
        input_otio = input_otio[0]
    # Project header & metadata
    mlt = ET.Element(
        'mlt',
        dict(
            version="6.23.0",
            title=input_otio.name,
            LC_NUMERIC="C",
            producer="main_bin",
        ),
    )
    rate = input_otio.duration().rate
    (rate_num, rate_den) = {
        23.98: (24000, 1001),
        29.97: (30000, 1001),
        59.94: (60000, 1001)
    }.get(round(float(rate), 2), (int(rate), 1))
    ET.SubElement(
        mlt, 'profile',
        dict(
            description='HD 1080p {} fps'.format(rate),
            frame_rate_num=str(rate_num),
            frame_rate_den=str(rate_den),
            width='1920',
            height='1080',
            display_aspect_num='16',
            display_aspect_den='9',
            sample_aspect_num='1',
            sample_aspect_den='1',
            colorspace='709',
            progressive='1',
        ),
    )

    # Build media library, indexed by url
    main_bin = ET.Element('playlist', dict(id='main_bin'))
    write_property(main_bin, 'kdenlive:docproperties.decimalPoint', '.')
    write_property(main_bin, 'kdenlive:docproperties.version', '0.98')
    write_property(main_bin, 'xml_retain', '1')

    # Process timeline markers
    write_property(main_bin, 'kdenlive:docproperties.guides',
                   write_markers(input_otio.tracks.markers))

    producer_count = 0

    media_prod = {}
    producer_array = {}
    for clip in input_otio.find_clips():
        producer, producer_count, key = _make_producer(
            producer_count, clip, mlt, rate, media_prod
        )
        if key is None:
            continue
        if producer is None:
            # There is already a producer for this clip
            # make sure it covers the clip's range
            producer = producer_array[key]
            prod_range = otio.opentime.TimeRange.range_from_start_end_time_inclusive(
                time(producer.get('in'), rate),
                time(producer.get('out'), rate)
            ).extended_by(clip.source_range)
            producer.set('in', clock(prod_range.start_time))
            producer.set('out', clock(prod_range.end_time_inclusive()))
            write_property(
                producer, 'length',
                str(prod_range.duration.to_frames())
            )
        producer_array[key] = producer

    for key in producer_array:
        producer = producer_array[key]
        producer_id = producer.get('id')
        kdenlive_id = read_property(producer, 'kdenlive:id')
        entry_in = producer.get('in')
        entry_out = producer.get('out')
        entry = ET.SubElement(
            main_bin, 'entry',
            {
                'producer': producer_id,
                'in': entry_in,
                'out': entry_out,
            },
        )
        write_property(entry, 'kdenlive:id', kdenlive_id)

    mlt.append(main_bin)

    # Background clip
    black = ET.SubElement(mlt, 'producer', {'id': 'black_track'})
    write_property(black, 'resource', 'black')
    write_property(black, 'mlt_service', 'color')

    # Timeline & tracks
    maintractor = ET.Element('tractor', {'global_feed': '1'})
    ET.SubElement(maintractor, 'track', {'producer': 'black_track'})

    unsupported_count = 0

    for i, track in enumerate(input_otio.tracks):
        is_audio = track.kind == otio.schema.TrackKind.Audio

        tractor_id = 'tractor{}'.format(i)
        subtractor = ET.Element('tractor', dict(id=tractor_id))
        write_property(subtractor, 'kdenlive:track_name', track.name)

        ET.SubElement(
            maintractor, 'track', dict(producer=tractor_id)
        )

        playlist = _make_playlist(
            2 * i,
            "video" if is_audio else "audio",
            subtractor,
            mlt,
        )
        dummy_playlist = _make_playlist(2 * i + 1, "both", subtractor, mlt)

        if is_audio:
            write_property(subtractor, 'kdenlive:audio_track', '1')
            write_property(playlist, 'kdenlive:audio_track', '1')

        # Track playlist
        for item in track:
            if isinstance(item, otio.schema.Gap):
                ET.SubElement(
                    playlist, 'blank', dict(length=clock(item.duration()))
                )
            elif isinstance(item, otio.schema.Clip):
                producer_id = "unsupported"
                reset_range = otio.opentime.TimeRange(
                    start_time=otio.opentime.RationalTime(0),
                    duration=item.source_range.duration,
                )
                clip_in = reset_range.start_time
                clip_out = reset_range.end_time_inclusive()
                kdenlive_id = "3"
                if isinstance(item.media_reference,
                              otio.schema.ExternalReference):
                    key = _prod_key_from_item(item, is_audio)
                    producer_id, kdenlive_id = media_prod[
                        key
                    ]
                    speed = key[2]
                    if speed is None:
                        speed = 1
                    source_range = otio.opentime.TimeRange(
                        otio.opentime.RationalTime(
                            item.source_range.start_time.value / speed,
                            item.source_range.start_time.rate,
                        ),
                        item.source_range.duration,
                    )
                    clip_in = source_range.start_time
                    clip_out = source_range.end_time_inclusive()
                elif isinstance(item.media_reference, otio.schema.GeneratorReference):
                    if item.media_reference.generator_kind == 'SolidColor':
                        producer_id, kdenlive_id = media_prod[
                            (
                                "color",
                                item.media_reference.parameters['color'],
                                None,
                                None,
                            )
                        ]
                    elif item.media_reference.generator_kind == 'SMPTEBars':
                        producer_id, kdenlive_id = media_prod[
                            (
                                "frei0r.test_pat_B",
                                "&lt;producer&gt;",
                                None,
                                None,
                            )
                        ]

                if producer_id == "unsupported":
                    unsupported_count += 1

                entry = ET.SubElement(
                    playlist, 'entry',
                    {
                        'producer': producer_id,
                        'in': clock(clip_in),
                        'out': clock(clip_out),
                    },
                )
                write_property(entry, 'kdenlive:id', kdenlive_id)

                # Clip effects
                for effect in item.effects:
                    kid = effect.effect_name
                    if kid in ['fadein', 'fade_from_black']:
                        filt = ET.SubElement(
                            entry, 'filter',
                            {
                                "in": clock(clip_in),
                                "out": clock(clip_in + effect.metadata['duration']),
                            },
                        )
                        write_property(filt, 'kdenlive_id', kid)
                        write_property(filt, 'end', '1')
                        if kid == 'fadein':
                            write_property(filt, 'mlt_service', 'volume')
                            write_property(filt, 'gain', '0')
                        else:
                            write_property(filt, 'mlt_service', 'brightness')
                            write_property(filt, 'start', '0')
                    elif effect.effect_name in ['fadeout', 'fade_to_black']:
                        filt = ET.SubElement(
                            entry, 'filter',
                            {
                                "in": clock(clip_out - effect.metadata['duration']),
                                "out": clock(clip_out),
                            },
                        )
                        write_property(filt, 'kdenlive_id', kid)
                        write_property(filt, 'end', '0')
                        if kid == 'fadeout':
                            write_property(filt, 'mlt_service', 'volume')
                            write_property(filt, 'gain', '1')
                        else:
                            write_property(filt, 'mlt_service', 'brightness')
                            write_property(filt, 'start', '1')
                    elif effect.effect_name in ['volume', 'brightness']:
                        filt = ET.SubElement(entry, 'filter')
                        write_property(filt, 'kdenlive_id', kid)
                        write_property(filt, 'mlt_service', kid)
                        write_property(filt, 'level',
                                       write_keyframes(effect.metadata['keyframes']))

            elif isinstance(item, otio.schema.Transition):
                print('Transitions handling to be added')

        mlt.extend((playlist, dummy_playlist, subtractor))

    mlt.append(maintractor)

    # in case we need it: add substitute source clip to be referred to
    # when meeting an unsupported clip
    if unsupported_count > 0:
        unsupported = ET.Element(
            'producer',
            {
                'id': 'unsupported',
                'in': '0',
                'out': '10000',
            },
        )
        write_property(unsupported, 'mlt_service', 'qtext')
        write_property(unsupported, 'family', 'Courier')
        write_property(unsupported, 'fgcolour', '#ff808080')
        write_property(unsupported, 'bgcolour', '#00000000')
        write_property(unsupported, 'text',
                       'Unsupported clip type')
        write_property(unsupported, 'kdenlive:clipname',
                       'Placeholder: Unsupported clip type')
        write_property(unsupported, 'kdenlive:id', '3')
        mlt.insert(1, unsupported)

        entry = ET.SubElement(
            main_bin, 'entry',
            dict(producer='unsupported'),
        )
        write_property(entry, 'kdenlive:id', '3')

    # Process marker/guide categories
    write_property(main_bin, 'kdenlive:docproperties.guidesCategories',
                   json.dumps(list(marker_categories.values())))

    return minidom.parseString(ET.tostring(mlt)).toprettyxml(
        encoding=sys.getdefaultencoding(),
    ).decode(sys.getdefaultencoding())


def _make_playlist(count, hide, subtractor, mlt):
    playlist_id = 'playlist{}'.format(count)
    playlist = ET.Element(
        'playlist',
        dict(id=playlist_id),
    )
    ET.SubElement(
        subtractor, 'track',
        dict(
            producer=playlist_id,
            hide=hide,
        ),
    )
    return playlist


def _decode_media_reference_url(url):
    return unquote(urlparse(url).path)


def _make_producer(count, item, mlt, frame_rate, media_prod, speed=None,
                   is_audio=None):
    producer = None
    service, resource, effect_speed, _ = _prod_key_from_item(item, is_audio)
    key = None
    if service and resource:
        producer_id = "producer{}".format(count)
        kdenlive_id = str(count + 4)  # unsupported starts with id 3

        key = (service, resource, speed, is_audio)
        # check not already in our library
        if key not in media_prod:
            if item.media_reference.available_range is not None:
                available_range = item.media_reference.available_range
            elif item.source_range is not None:
                available_range = item.source_range
            else:
                return None, count
            if service == "qimage":
                print("Image")
                available_range = otio.opentime.TimeRange.range_from_start_end_time(
                    otio.opentime.RationalTime(0, frame_rate),
                    available_range.end_time_exclusive()
                )
            # add ids to library
            media_prod[key] = producer_id, kdenlive_id
            producer = ET.SubElement(
                mlt, 'producer',
                {
                    'id': producer_id,
                    'in':
                        clock(available_range.start_time),
                    'out':
                        clock(available_range.end_time_inclusive())
                },
            )
            write_property(producer, 'global_feed', '1')
            duration = available_range.duration.rescaled_to(
                frame_rate
            )
            if speed is not None:
                kdenlive_id = media_prod[(service, resource, None, None)][1]
                write_property(producer, 'mlt_service', "timewarp")
                write_property(producer,
                               'resource', ":".join((str(speed), resource)))
                write_property(producer, 'warp_speed', str(speed))
                write_property(producer, 'warp_resource', resource)
                write_property(producer, 'warp_pitch', "0")
                write_property(producer,
                               'set.test_audio', "0" if is_audio else "1")
                write_property(producer,
                               'set.test_image', "1" if is_audio else "0")
                start_time = otio.opentime.RationalTime(
                    round(
                        available_range.start_time.value /
                        speed
                    ),
                    available_range.start_time.rate,
                )
                duration = otio.opentime.RationalTime(
                    round(duration.value / speed),
                    duration.rate,
                )
                producer.set(
                    "out",
                    clock(
                        otio.opentime.TimeRange(
                            start_time,
                            duration,
                        ).end_time_inclusive()
                    ),
                )
            else:
                write_property(producer, 'mlt_service', service)
                write_property(producer, 'resource', resource)
                if item.name:
                    write_property(producer, 'kdenlive:clipname', item.name)
            write_property(
                producer, 'length',
                str(duration.to_frames()),
            )
            write_property(producer, 'kdenlive:id', kdenlive_id)
            if (isinstance(item.media_reference,
                           otio.schema.GeneratorReference) and
                    item.media_reference.generator_kind == 'SMPTEBars'):
                # set the type of the test pattern to SMPTE (value 4)
                write_property(producer, '0', '4')

            count += 1

        # create time warped version
        if speed is None and effect_speed is not None:
            # Make video resped producer
            _, count, _ = _make_producer(
                count, item, mlt, frame_rate, media_prod, effect_speed, False
            )
            # Make audio resped producer
            _, count, _ = _make_producer(
                count, item, mlt, frame_rate, media_prod, effect_speed, True
            )

    return producer, count, key


def _prod_key_from_item(item, is_audio):
    service = None
    resource = None
    speed = None
    if isinstance(
        item.media_reference,
        (otio.schema.ExternalReference, otio.schema.MissingReference),
    ):
        if isinstance(item.media_reference, otio.schema.ExternalReference):
            resource = _decode_media_reference_url(item.media_reference.target_url)
        elif isinstance(item.media_reference, otio.schema.MissingReference):
            resource = item.name

        ext_lower = os.path.splitext(resource)[1].lower()
        if ext_lower == ".kdenlive":
            service = "xml"
        elif ext_lower in (
            ".png", ".jpg", ".jpeg"
        ):
            service = "qimage"
        else:
            service = "avformat-novalidate"

        for effect in item.effects:
            if (isinstance(effect, otio.schema.LinearTimeWarp) and
               not isinstance(effect, otio.schema.FreezeFrame)):
                if speed is None:
                    speed = 1
                speed *= effect.time_scalar
    elif isinstance(item.media_reference, otio.schema.GeneratorReference):
        if item.media_reference.generator_kind == 'SolidColor':
            service = 'color'
            resource = item.media_reference.parameters['color']
        elif item.media_reference.generator_kind == 'SMPTEBars':
            service = 'frei0r.test_pat_B'
            resource = '&lt;producer&gt;'
    return service, resource, speed, None if speed is None else is_audio


if __name__ == '__main__':
    timeline = read_from_string(
        open('tests/sample_data/kdenlive_example.kdenlive', 'r').read())
    print(str(timeline).replace('otio.schema', "\notio.schema"))
    xml = write_to_string(timeline)
    print(str(xml))
