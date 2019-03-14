import itertools
from pprint import pprint

import fire
from bluesky.utils import install_qt_kicker
from rapidz import Stream, move_to_first
from rapidz.link import link
from shed import SimpleToEventStream
from xpdan.pipelines.to_event_model import (
    to_event_stream_no_ind,
    to_event_stream_with_ind,
)
from xpdan.pipelines.tomo import (
    pencil_tomo,
    tomo_event_stream,
    full_field_tomo,
)
from xpdan.vend.callbacks import CallbackBase
from xpdan.vend.callbacks.core import RunRouter, Retrieve
from xpdan.vend.callbacks.zmq import Publisher, RemoteDispatcher
from xpdconf.conf import glbl_dict
from xpdtools.pipelines.tomo import (
    tomo_prep,
    tomo_pipeline_piecewise,
    tomo_pipeline_theta,
    tomo_stack_2D,
)

pencil_order_2D = [
    pencil_tomo,
    tomo_prep,
    tomo_pipeline_piecewise,
    tomo_event_stream,
]

pencil_order_3D = [
    pencil_tomo,
    tomo_prep,
    tomo_pipeline_piecewise,
    tomo_stack_2D,
    tomo_event_stream,
]

full_field_order = [full_field_tomo, tomo_pipeline_theta, tomo_event_stream]


class PencilTomoCallback(CallbackBase):
    """This class caches and passes documents into the pencil tomography
    pipeline.

    The translation and rotation motors are inspected from the data as are the
    scalar quantities of interest.

    This class acts as a descriptor router for documents"""

    def __init__(self, pipeline_factory, publisher, **kwargs):
        self.pipeline_factory = pipeline_factory
        self.publisher = publisher

        self.start_doc = {}
        self.dim_names = []
        self.translation = None
        self.rotation = None
        self.stack = None
        self.sources = []
        self.kwargs = kwargs

    def start(self, doc):
        self.start_doc = doc
        self.dim_names = [
            d[0][0]
            for d in doc.get("hints", {}).get("dimensions")
            if d[0][0] != "time"
        ]
        tomo_dict = doc["tomo"]
        self.translation = tomo_dict["translation"]
        self.rotation = tomo_dict["rotation"]
        if 'stack' in tomo_dict:
            self.stack = tomo_dict['stack']

    def descriptor(self, doc):
        indep_vars = list(
                itertools.chain.from_iterable(
                    [doc["object_keys"][n] for n in self.dim_names]
                ))

        # TODO: only listen to primary stream
        dep_shapes = {
            n: doc["data_keys"][n]["shape"]
            for n in doc["data_keys"]
            if (n not in indep_vars) and (doc["data_keys"][n]['dtype'] not in ['PDFConfig', 'AzimuthalIntegrator'])
        }

        # Only compute QOIs on scalars, currently
        qois = [k for k, v in dep_shapes.items() if len(v) == 0]
        rotation_pos = self.start_doc["motors"].index(self.rotation)
        translation_pos = self.start_doc["motors"].index(self.translation)

        self.sources = [Stream(stream_name=str(qoi)) for qoi in qois]
        pipelines = [
            self.pipeline_factory(
                source=s,
                qoi_name=qoi,
                translation=self.translation,
                rotation=self.rotation,
                stack=self.stack,
                x_dimension=self.start_doc["shape"][translation_pos],
                th_dimension=self.start_doc["shape"][rotation_pos],
                **self.kwargs,
            )
            for s, qoi in zip(self.sources, qois)
        ]
        for p in pipelines:
            to_event_stream_no_ind(
                *[node for node in p.values() if isinstance(node, SimpleToEventStream)],
                publisher=self.publisher
            )

        for s in self.sources:
            s.emit(("start", self.start_doc))
            s.emit(("descriptor", doc))

    def event(self, doc):
        for s in self.sources:
            s.emit(("event", doc))

    def stop(self, doc):
        for s in self.sources:
            s.emit(("stop", doc))
        # Need to destroy pipeline


class FullFieldTomoCallback(Retrieve):
    """This class caches and passes documents into the pencil tomography
        pipeline.

        The translation and rotation motors are inspected from the data as are the
        scalar quantities of interest.

        This class acts as a descriptor router for documents"""

    def __init__(self, pipeline_factory, publisher, handler_reg,
                 root_map=None, executor=None,
                 **kwargs):
        super().__init__(handler_reg, root_map, executor)
        self.pipeline_factory = pipeline_factory
        self.publisher = publisher

        self.start_doc = {}
        self.dim_names = []
        self.rotation = None
        self.sources = []
        self.kwargs = kwargs

    def start(self, doc):
        super().start(doc)
        self.start_doc = doc
        self.dim_names = [
            d[0][0]
            for d in doc.get("hints", {}).get("dimensions")
            if d[0][0] != "time"
        ]
        self.rotation = doc["tomo"]["rotation"]

    def descriptor(self, doc):
        # TODO: only listen to primary stream
        dep_shapes = {
            n: doc["data_keys"][n]["shape"]
            for n in doc["data_keys"]
            if n
            not in list(
                itertools.chain.from_iterable(
                    [doc["object_keys"][n] for n in self.dim_names]
                )
            )
        }

        # Only compute QOIs on scalars, currently
        qois = [k for k, v in dep_shapes.items() if len(v) == 2]

        self.sources = [Stream(stream_name=str(qoi)) for qoi in qois]
        pipelines = [
            self.pipeline_factory(
                source=s, qoi_name=qoi, rotation=self.rotation, **self.kwargs
            )
            for s, qoi in zip(self.sources, qois)
        ]
        for p in pipelines:
            to_event_stream_no_ind(
                p["sinogram_tes"], p["rec_tes"], publisher=self.publisher
            )

        for s in self.sources:
            s.emit(("start", self.start_doc))
            s.emit(("descriptor", doc))

    def event(self, doc):
        doc = super().event(doc)
        for s in self.sources:
            s.emit(("event", doc))

    def stop(self, doc):
        for s in self.sources:
            s.emit(("stop", doc))
        # Need to destroy pipeline


def tomo_callback_factory(doc, publisher, handler_reg=None, **kwargs):
    # TODO: Eventually extract from plan hints?
    tomo_dict = doc.get("tomo", {})
    if tomo_dict.get("type", None) == "pencil":
        if "stack" in tomo_dict:
            return PencilTomoCallback(
                lambda **inner_kwargs: link(*pencil_order_3D, **inner_kwargs),
                publisher,
                **kwargs,
            )

        else:
            return PencilTomoCallback(
                lambda **inner_kwargs: link(*pencil_order_2D, **inner_kwargs),
                publisher,
                **kwargs,
            )
    elif tomo_dict.get("type", None) == "full_field":
        return FullFieldTomoCallback(
            lambda **inner_kwargs: link(*full_field_order, **inner_kwargs),
            publisher,
            handler_reg,
            **kwargs,
        )


def run_server(
    outbound_proxy_address=glbl_dict["outbound_proxy_address"],
    inbound_proxy_address=glbl_dict["inbound_proxy_address"],
    outbound_prefix=(b"raw", b"an", b"qoi"),
    inbound_prefix=b"tomo",
    _publisher=None,
    **kwargs,
):
    """Server for performing tomographic reconstructions

    Parameters
    ----------
    outbound_proxy_address : str, optional
        The outbound ip address for the ZMQ server. Defaults to the value
        from the global dict
    inbound_proxy_address : str, optional
        The inbound ip address for the ZMQ server. Defaults to the value
        from the global dict
    outbound_prefix : bytes or sequence of bytes
        The data channels to listen to
    inbound_prefix : bytes
        The data channel to publish to
    kwargs : dict
        kwargs passed to the reconstruction, for instance ``algorithm`` could
        be passed in with the associated tomopy algorithm to change the
        reconstructgion algorithm from gridrec to something else.

    """
    print(kwargs)
    db = glbl_dict['exp_db']
    handler_reg = db.reg.handler_reg
    if _publisher is None:
        publisher = Publisher(inbound_proxy_address, prefix=inbound_prefix)
    else:
        publisher = _publisher

    rr = RunRouter(
        [lambda x: tomo_callback_factory(x, publisher=publisher,
                                         handler_reg=handler_reg, **kwargs)]
    )

    d = RemoteDispatcher(outbound_proxy_address, prefix=outbound_prefix)
    install_qt_kicker(loop=d.loop)

    d.subscribe(rr)
    print("Starting Tomography Server")
    d.start()


def run_main():
    fire.Fire(run_server)


if __name__ == "__main__":
    run_main()
