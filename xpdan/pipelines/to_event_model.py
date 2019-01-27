"""Event Model mirror of xpdtools.pipelines.raw_pipeline meant to accept nodes
from the raw pipeline and convert them to Event Model"""
from shed.simple import SimpleToEventStream, AlignEventStreams
from xpdtools.tools import overlay_mask, splay_tuple


def to_event_stream_with_ind(raw_stripped, *nodes, publisher, **kwargs):
    for node in nodes:
        merge = AlignEventStreams(raw_stripped, node)
        merge.starsink(publisher)
    return locals()


def to_event_stream_no_ind(*nodes, publisher, **kwargs):
    for node in nodes:
        node.starsink(publisher)
    return locals()


def image_process(dark_corrected_foreground, bg_corrected_img, **kwargs):
    dark_corrected_tes = SimpleToEventStream(
        dark_corrected_foreground,
        ("dark_corrected_img",),
        analysis_stage="dark_sub",
    )
    bg_corrected_tes = SimpleToEventStream(
        bg_corrected_img, ("bg_corrected_img",), analysis_stage="bg_sub"
    )
    return locals()


def calibration(geometry, **kwargs):
    geometry_tes = SimpleToEventStream(
        geometry, ("calibration",), analysis_stage="calib"
    )
    return locals()


def gen_mask(mask, pol_corrected_img, **kwargs):
    mask_tes = SimpleToEventStream(mask, ("mask",), analysis_stage="mask")

    mask_overlay_tes = SimpleToEventStream(
        pol_corrected_img.combine_latest(mask).starmap(overlay_mask),
        ("mask_overlay",),
        analysis_stage="mask_overlay",
    )
    return locals()


def integration(mean, q, tth, std=None, median=None, **kwargs):
    merge_names = ["mean"]
    merge_streams = []
    if std:
        merge_names += ["std"]
        merge_streams += [std]
    if median:
        merge_names += ["median"]
        merge_streams += [median]
    if merge_streams:
        merge = mean.zip(*merge_streams)
        # need to splay so we have everything at the same level
        integration_merge = merge.combine_latest(q, tth, emit_on=0).map(
            splay_tuple
        )
    else:
        merge = mean
        integration_merge = merge.combine_latest(q, tth, emit_on=0)

    merge_names += ["q", "tth"]
    integration_tes = SimpleToEventStream(
        integration_merge,
        merge_names,
        analysis_stage="integration",
        # TODO: might push q/tth into the same list
        hints=dict(dimensions=[(["q"], "primary"), (["tth"], "primary")]),
    )
    return locals()


def pdf_gen(fq, sq, pdf, **kwargs):
    fq_tes = SimpleToEventStream(
        fq,
        ("q", "fq", "config"),
        analysis_stage="fq",
        hints=dict(dimensions=[(["q"], "primary")]),
    )
    sq_tes = SimpleToEventStream(
        fq,
        ("q", "sq", "config"),
        analysis_stage="sq",
        hints=dict(dimensions=[(["q"], "primary")]),
    )

    pdf_tes = SimpleToEventStream(
        pdf,
        ("r", "gr", "config"),
        analysis_stage="pdf",
        hints=dict(dimensions=[(["r"], "primary")]),
    )
    return locals()


pipeline_order = [image_process, calibration, gen_mask, integration, pdf_gen]
