#!/usr/bin/env python

from distutils.core import setup

from catkin_pkg.python_setup import generate_distutils_setup

setup(
    **generate_distutils_setup(
        packages=[
            "aiorosbridge",
            "aiorosbridge._api",
            "aiorosbridge._library",
            "aiorosbridge._protocol",
            "aiorosbridge.server",
        ],
        package_data={
            "aiorosbridge": ["py.typed"],
        },
    )
)
