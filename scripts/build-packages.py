#!/usr/bin/env python

import os
import glob
import subprocess as sp
import argparse
import sys

import nose
from conda_build.metadata import MetaData
from toposort import toposort_flatten

PYTHON_VERSIONS = ["27", "35"]
CONDA_NPY = "110"


def get_metadata(recipes):
    for recipe in recipes:
        print("Reading recipe", recipe, file=sys.stderr)
        yield MetaData(recipe)


# inspired by conda-build-all from https://github.com/omnia-md/conda-recipes
def toposort_recipes(recipes):
    metadata = list(get_metadata(recipes))

    name2recipe = {
        meta.get_value("package/name"): recipe
        for meta, recipe in zip(metadata, recipes)
    }

    def get_inner_deps(dependencies):
        for dep in dependencies:
            name = dep.split()[0]
            if name in name2recipe:
                yield name

    dag = {
        meta.get_value("package/name"): set(
            get_inner_deps(meta.get_value("requirements/build", [])))
        for meta in metadata
    }
    return [name2recipe[name] for name in toposort_flatten(dag)]


def conda_index():
    index_dirs = [
        "/anaconda/conda-bld/linux-64",
        "/anaconda/conda-bld/osx-64",
    ]
    sp.run(["conda", "index"] + index_dirs, check=True, stdout=sp.PIPE)


def build_recipe(recipe):
    errors = 0
    builds = 0
    conda_index()
    for py in PYTHON_VERSIONS:
        try:
            builds += 1
            out = None if args.verbose else sp.PIPE
            sp.run(["conda", "build", "--no-anaconda-upload", "--numpy",
                     CONDA_NPY, "--python", py, "--skip-existing", "--quiet",
                     recipe],
                    stderr=out, stdout=out, check=True, universal_newlines=True)
        except sp.CalledProcessError as e:
            if e.stdout is not None:
                print(e.stdout)
                print(e.stderr)
            errors += 1
    if errors == builds:
        # fail if all builds result in an error
        assert False


def filter_recipes(recipes):
    msgs = lambda py: [
        msg for msg in
        sp.run(
            ["conda", "build", "--numpy", CONDA_NPY, "--python", py,
             "--skip-existing", "--output"] + recipes,
            check=True, stdout=sp.PIPE, universal_newlines=True
        ).stdout.split("\n")
        if "Ignoring non-recipe" not in msg
    ][1:-1]

    for item in zip(recipes, *map(msgs, PYTHON_VERSIONS)):
        recipe = item[0]
        msg = item[1:]

        if all("already built, skipping" in m for m in msg):
            print("Skipping recipe", recipe, file=sys.stderr)
        else:
            yield recipe


def test_recipes():
    if args.packages:
        recipes = [os.path.join(args.repository, "recipes", package)
                   for package in args.packages]
    else:
        recipes = list(glob.glob(os.path.join(args.repository, "recipes",
                                              "*")))

    # ensure that packages which need a build are built in the right order
    recipes = toposort_recipes(list(filter_recipes(recipes)))

    # build packages
    for recipe in recipes:
        yield build_recipe, recipe

    # upload builds
    if os.environ.get("TRAVIS_BRANCH") == "master" and os.environ.get(
        "TRAVIS_PULL_REQUEST") == "false":
        for recipe in recipes:
            packages = set()
            for py in PYTHON_VERSIONS:
                packages.add(sp.run(["conda", "build", "--output",
                                     "--numpy", CONDA_NPY, "--python",
                                     py, recipe], stdout=sp.PIPE,
                                     check=True).stdout.strip().decode())
            for package in packages:
                if os.path.exists(package):
                    try:
                        sp.run(["anaconda", "-t",
                                os.environ.get("ANACONDA_TOKEN"),
                                "upload", package], stdout=sp.PIPE, check=True)
                    except sp.CalledProcessError as e:
                        if b"already exists" in e.stdout:
                            # ignore error assuming that it is caused by existing package
                            pass
                        raise e


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Build bioconda packages")
    p.add_argument("--repository",
                   default="/bioconda-recipes",
                   help="Path to checkout of bioconda recipes repository.")
    p.add_argument("--packages",
                   nargs="+",
                   help="A specific package to build.")
    p.add_argument("-v", "--verbose",
                   help="Make output more verbose for local debugging",
                   default=False,
                   action="store_true")

    global args
    args = p.parse_args()

    sp.run(["gcc", "--version"], check=True)
    try:
        sp.run(["ldd", "--version"], check=True)
    except:
        pass

    nose.main(argv=sys.argv[:1], defaultTest="__main__")
