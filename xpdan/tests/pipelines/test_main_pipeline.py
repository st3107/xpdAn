import time

import pytest
from shed.simple import SimpleToEventStream as ToEventStream
from streamz_ext import Stream, move_to_first
from xpdan.pipelines.main import pipeline_order
from streamz_ext.link import link


@pytest.mark.parametrize("exception", [True, False])
@pytest.mark.parametrize("background", [True, False])
def test_main_pipeline(
    exp_db, fast_tmp_dir, start_uid3, start_uid1, background, exception
):
    namespace = link(
        *pipeline_order, raw_source=Stream(stream_name="raw source")
    )
    filler = namespace["filler"]
    bg_query = namespace["bg_query"]
    bg_dark_query = namespace["bg_dark_query"]
    fg_dark_query = namespace["fg_dark_query"]
    mean = namespace["mean"]
    iq_comp = namespace["iq_comp"]
    q = namespace["q"]
    raw_source = namespace["raw_source"]

    iq_em = ToEventStream(mean.combine_latest(q, emit_on=0), ("iq", "q"))
    iq_em.sink(print)

    # reset the DBs so we can use the actual db
    filler.db = exp_db
    for a in [bg_query, bg_dark_query, fg_dark_query]:
        a.kwargs["db"] = exp_db

    limg = []
    move_to_first(namespace["bg_corrected_img"].sink(lambda x: limg.append(x)))
    lbgc = mean.sink_to_list()
    lpdf = iq_comp.sink_to_list()
    t0 = time.time()
    if background:
        uid = start_uid1
    else:
        uid = -1
    for nd in exp_db[uid].documents(fill=True):
        name, doc = nd
        if name == "start":
            if exception:
                doc["bt_wavelength"] = "bla"
            nd = (name, doc)
        try:
            raw_source.emit(nd)
        except ValueError:
            pass
    t1 = time.time()
    print(t1 - t0)
    n_events = len(list(exp_db[-1].events()))
    assert len(limg) == n_events
    if exception:
        assert_lbgc = 0
    else:
        assert_lbgc = n_events
    assert len(lbgc) == assert_lbgc
    assert len(lpdf) == assert_lbgc
    assert iq_em.state == "stopped"
