#!/usr/bin/env python3

import argparse
import os
import os.path
import re
import sys
import urllib.request
import hashlib
import shutil
import json
import tarfile
import tempfile
import zipfile
import mmap
from pep508_parser import parser
from pipoe import licenses
from functools import partial
from collections import namedtuple
from pprint import pformat

import pkginfo

BB_TEMPLATE = """
SUMMARY = "{summary}"
HOMEPAGE = "{homepage}"
AUTHOR = "{author} <{author_email}>"
LICENSE = "{license}"
LIC_FILES_CHKSUM = "file://{license_file};md5={license_md5}"

inherit setuptools{setuptools}

SRC_URI = "{src_uri}"
SRC_URI[md5sum] = "{md5}"
SRC_URI[sha256sum] = "{sha256}"

S = "${{WORKDIR}}/{src_dir}"

DEPENDS += " {build_dependencies}"
RDEPENDS_${{PN}} = "{dependencies}"

BBCLASSEXTEND = "native nativesdk"
"""

BB_TEMPLATE_PYPI = """
SUMMARY = "{summary}"
HOMEPAGE = "{homepage}"
AUTHOR = "{author} <{author_email}>"
LICENSE = "{license}"
LIC_FILES_CHKSUM = "file://{license_file};md5={license_md5}"

inherit setuptools{setuptools} pypi

SRC_URI[md5sum] = "{md5}"
SRC_URI[sha256sum] = "{sha256}"

PYPI_PACKAGE = "{pypi_package}"{pypi_package_ext}

DEPENDS += " {build_dependencies}"
RDEPENDS_${{PN}} = "{dependencies}"

BBCLASSEXTEND = "native nativesdk"
"""


BB_EXTRA_TEMPLATE = """
SUMMARY = "{summary}"
HOMEPAGE = "{homepage}"
AUTHOR = "{author} <{author_email}>"

RDEPENDS_${{PN}} = "{dependencies}"

inherit packagegroup

BBCLASSEXTEND = "native nativesdk"
"""


Package = namedtuple(
    "Package",
    [
        "name",
        "version",
        "summary",
        "homepage",
        "author",
        "author_email",
        "license",
        "license_file",
        "license_md5",
        "src_dir",
        "src_uri",
        "src_md5",
        "src_sha256",
        "dependencies",
        "build_dependencies",
    ],
)

Dependency = namedtuple("Dependency", ["name", "version", "extra"])


def md5sum(path):
    with open(path, mode="rb") as f:
        d = hashlib.md5()
        for buf in iter(partial(f.read, 128), b""):
            d.update(buf)
    return d.hexdigest()


def sha256sum(path):
    with open(path, mode="rb") as f:
        d = hashlib.sha256()
        for buf in iter(partial(f.read, 128), b""):
            d.update(buf)
    return d.hexdigest()


def package_to_bb_name(package):
    return package.lower().replace("_", "-").replace(".", "-")


def translate_license(license, classifiers, default_license):
    try:
        try:
            if license not in [ '', None ]:
                return licenses.LICENSES[license.strip("'").strip('"')]
        except:
            pass

        for classifier in classifiers:
            if classifier.startswith("License"):
                return licenses.LICENSES[classifier]

        raise Exception("No license found")
    except:
        if default_license:
            return default_license

        print("Failed to translate license: {}".format(license))
        mapping = input("Please enter a valid license name: ")
        licenses.LICENSES[license] = mapping
        return mapping


def unpack_package(file):
    tmpdir = "{}.d".format(file)

    if os.path.exists(tmpdir):
        shutil.rmtree(tmpdir)

    os.mkdir(tmpdir)
    shutil.unpack_archive(file, extract_dir=tmpdir)

    return tmpdir


def get_file_extension(uri):
    extensions = ["tar", "tar.gz", "tar.bz2", "tar.xz", "zip"]
    for extension in extensions:
        if uri.endswith(extension):
            return extension
    raise Exception("Extension not supported: {}".format(uri))

def package_to_bb_build_depends(package_name):
    name = package_name.split('<')[0].split('>')[0].split('~')[0].split('=')[0].strip()
    return "${PYTHON_PN}-" + package_to_bb_name(name) + "-native"

def gather_package_build_depends(name, data):
    build_deps = []

    if re.match(b"^(\s*)$", name):
        return build_deps

    # Check if it's a variable
    match = re.search(name + b" = (.*)", data)
    if match:
        # This is a variable check his contents
        for bd in match.group(1).replace(b'[', b'').replace(b']', b'').split(b","):
            match = re.match('^\w\S+', bd.decode("utf-8").replace("'","").replace("\"", "").strip())
            if match:
                build_deps.append(package_to_bb_build_depends(match.group(0)))
    else:
        # This is a regular field
        build_deps.append(package_to_bb_build_depends(name.decode("utf-8").replace("'","").replace("\"", "")))


    return build_deps


def get_package_file_info(package, version, uri):
    extension = get_file_extension(uri)
    with tempfile.TemporaryDirectory() as tmp:
        build_deps = []
        output = os.path.join(str(tmp), "{}_{}.{}".format(package, version, extension))

        if os.path.exists(output):
            os.remove(output)

        urllib.request.urlretrieve(uri, output)

        tmpdir = unpack_package(output)
        src_dir = os.listdir(tmpdir)[0]

        src_files = os.listdir("{}/{}".format(tmpdir, src_dir))

        try:
            license_file = next(
                f
                for f in src_files
                if ("license" in f.lower() or "copying" in f.lower())
                and not os.path.isdir(os.path.join(tmpdir, src_dir, f))
            )
        except:
            license_file = None

        # Try to catch build depends into setup.py file
        setup_py = os.path.join(tmpdir, src_dir, "setup.py")
        if os.path.exists(setup_py):
            if license_file is None:
                license_file = "setup.py"
            with open(setup_py, 'r+') as f:
                data = mmap.mmap(f.fileno(), 0)
                match = re.search(b'^(\s*)setup_requires( *)=( *)([\[|\(]*)(.*)([\]|\)]*)', data, re.MULTILINE)
                if match:
                    for bd in match.group(5).replace(b'[', b'').replace(b']', b'').replace(b'(', b'').replace(b')', b'').strip().split(b","):
                         build_deps.extend(gather_package_build_depends(bd, data))

        pyproject_toml = os.path.join(tmpdir, src_dir, "pyproject.toml")
        if os.path.exists(pyproject_toml):
            if license_file is None:
                license_file = "pyproject.toml"
            with open(pyproject_toml, 'r+') as f:
                data = mmap.mmap(f.fileno(), 0)
                match = re.search(b'^(\s*)dependencies( *)=( *)([\[|\(]*)(.*)([\]|\)]*)', data, re.MULTILINE)
                if match:
                    for bd in match.group(5).replace(b'[', b'').replace(b']', b'').replace(b'(', b'').replace(b')', b'').strip().split(b","):
                         build_deps.extend(gather_package_build_depends(bd, data))



        license_path = os.path.join(tmpdir, src_dir, license_file)
        license_md5 = md5sum(license_path)
        src_md5 = md5sum(output)
        src_sha256 = sha256sum(output)

        os.remove(output)
        shutil.rmtree(tmpdir)

        return (src_md5, src_sha256, src_dir, license_file, license_md5, build_deps)


def decide_version(spec):
    version = spec[2]
    if version:
        version = version[0]
        relation = version[0]
        version = version[1]

        if relation == "==":
            return version
        elif relation == ">=":
            return None
        elif relation == "<=":
            return version
        else:
            return None
    else:
        return None


def decide_extra(spec):
    extra = spec[3]
    if extra:
        if extra[0] == "and":
            return extra[2][2]
        else:
            return extra[2]
    else:
        return None


def parse_requires_dist(requires_dist):
    spec = parser.parse(requires_dist)
    ret = Dependency(spec[0], decide_version(spec), decide_extra(spec))
    return ret

def pkg_size(pkg):
    # whl is omitted as we prefer source package
    extensions = ["tar", "tar.gz", "tar.bz2", "tar.xz"]
    for extension in extensions:
        if pkg["url"].endswith(extension):
            return pkg["size"]
    if pkg["url"].endswith("zip"):
        return pkg["size"] * 10
    return pkg["size"] * 10000


def fetch_requirements_from_remote_package(info, version):
    """ Looks up requires_dist from an actual package """

    if "releases" in info:
        # Version must exists, otherwise previous steps failed
        pkg_versions = info["releases"][version]

        # If we must fetch a package, lets fetch the smallest one
        pkg_url = sorted(pkg_versions, key=pkg_size, reverse=False)[0]["url"]
        filename = pkg_url.split("/")[-1]

        # Select the appropriate parser from pkginfo based on the filename
        parse = None
        if filename.endswith(".tar.gz") or filename.endswith(".zip") or filename.endswith(".tar.xz") or filename.endswith(".tar.bz2") or filename.endswith(".tar"):
            parse = pkginfo.SDist
        elif filename.endswith(".whl"):
            parse = pkginfo.Wheel
        elif filename.endswith(".egg"):
            parse =pkginfo.BDist
        else:
            raise RuntimeError("Unsupported fileformat for package introspection: {}".format(filename))
    else:
        pkg_url = info["info"]["url"]
        filename = pkg_url.split("/")[-1]
        parse = pkginfo.SDist

    # Download the package and read the MANIFEST
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, filename)
        urllib.request.urlretrieve(pkg_url, path)
        return parse(path).requires_dist


def get_package_dependencies(requires_dist, follow_extras=False):
    deps = []

    if requires_dist:
        for dep in requires_dist:
            d = parse_requires_dist(dep)
            if d.extra and not follow_extras:
                continue
            deps.append(d)

    return deps


PROCESSED_PACKAGES = []

def compare_versions(version1: str, version2: str) -> int:
    """
    Compares two pip package versions without using external modules.
    Returns:
        -1 if version1 < version2
         0 if version1 == version2
         1 if version1 > version2
    """

    if not version1:
        return -1

    def normalize(version: str):
        """Converts version string into a list of integers for comparison."""
        return [int(part) if part.isdigit() else part for part in version.replace("-", ".").split(".")]

    v1_parts = normalize(version1)
    v2_parts = normalize(version2)

    for v1, v2 in zip(v1_parts, v2_parts):
        if v1 == v2:
            continue
        if v1 < v2:
            return -1
        if v1 > v2:
            return 1

    return 0  # Versions are equal



def check_package_already_processed(package_name, version,
                                    processed_packages, packages):
    all_packages = processed_packages + packages[0]
    for package in all_packages:
        if package_name == package.name:
            result = compare_versions(version, package.version)
            if result != 1:
                return True
            print("  {} [WARNING] Package {} version needed {} found {}"
                  .format("|", package_name, version, package.version))

    return False


def get_package_info(
    package,
    version=None,
    packages=None,
    indent=0,
    extra=None,
    follow_extras=False,
    default_license=None,
):
    global PROCESSED_PACKAGES

    package_name = package.split('[')[0]
#    extra_needed = package.split('[')[1].replace("]", "")

    if not packages:
        packages = [[]]
    elif check_package_already_processed(package_name, version, PROCESSED_PACKAGES, packages):
        return packages[0]

    indent_str = ""
    if indent:
        indent_str = "|" + (indent - 2) * "-" + " "

    extra_str = ""
    if extra:
        extra_str = "[{}]".format(extra)

    print(
        "  {}{}{}{}".format(
            indent_str, package, extra_str, "=={}".format(version) if version else ""
        )
    )

    try:
        if version:
            if re.search('\*', version):
                url = "https://pypi.org/pypi/{}/json".format(package_name)
                response = urllib.request.urlopen(url).read().decode(encoding="UTF-8")
                info = json.loads(response)
                pv = []
                v = version.split('.')
                print("fuzzy version {} ".format(v))
                for i in info["releases"]:
                    tv = i.split('.')
                    found=True
                    for j in enumerate(v):
                        if j[1] == '*':
                            break;
                        if j[1] != tv[j[0]]:
                            found=False
                            break
                    if found:
                        pv.append(i)
                version = pv[-1]


            url = "https://pypi.org/pypi/{}/{}/json".format(package_name, version)
        else:
            url = "https://pypi.org/pypi/{}/json".format(package_name)

        response = urllib.request.urlopen(url).read().decode(encoding="UTF-8")
        info = json.loads(response)

        name = package_name
        if not version:
            version = info["info"]["version"]
        summary = info["info"]["summary"].replace('\n', ' \\\n')
        homepage = info["info"]["home_page"]
        author = info["info"]["author"]
        author_email = info["info"]["author_email"]
        license = translate_license(info["info"]["license"],
                                    info["info"]["classifiers"],
                                    default_license)

        try:
            if "releases" in info and version in info["releases"]:
                version_info = next(
                    i for i in info["releases"][version] if i["packagetype"] == "sdist"
                )
            else:
                version_info = info["info"]
                if "url" not in version_info and "urls" in info:
                    url = next(
                        i for i in info["urls"] if i["packagetype"] == "sdist"
                    )
                    version_info["url"] = url["url"]
        except Exception as e:
            raise Exception("No sdist package can be found.")

        src_uri = version_info["url"]
        src_md5, src_sha256, src_dir, license_file, license_md5, build_deps = get_package_file_info(
            package_name, version, src_uri
        )

        requires_dist = info["info"]["requires_dist"]

        # Only parse if requires_dist is missing, e.g. sentry-sdk
        if requires_dist is None:
            requires_dist = fetch_requirements_from_remote_package(info, version)

        dependencies = get_package_dependencies(requires_dist, follow_extras=follow_extras)

        package = Package(
            name,
            version,
            summary,
            homepage,
            author,
            author_email,
            license,
            license_file,
            license_md5,
            src_dir,
            src_uri,
            src_md5,
            src_sha256,
            dependencies,
            build_deps,
        )

        packages[0].append(package)
        PROCESSED_PACKAGES.append(package)

        for dependency in dependencies:
            get_package_info(
                dependency.name,
                version=dependency.version,
                packages=packages,
                indent=indent + 2,
                extra=dependency.extra,
                follow_extras=follow_extras,
                default_license=default_license,
            )

    except Exception as e:
        print(
            "  {} [ERROR] Failed to gather {} ({})".format(indent_str, package, str(e))
        )

    return packages[0]


def generate_recipe(package, outdir, python, is_extra=False, use_pypi=False):
    basename = "{}-{}_{}.bb".format(
        python, package_to_bb_name(package.name), package.version
    )
    bbfile = os.path.join(outdir, basename)

    print("  {}".format(basename))

    if is_extra:
        output = BB_EXTRA_TEMPLATE.format(
            summary=package.summary,
            homepage=package.homepage,
            author=package.author,
            author_email=package.author_email,
            dependencies=" ".join(
                [
                    "{}-{}".format(python, package_to_bb_name(dep.name))
                    for dep in package.dependencies
                ]
            ),
        )
    else:
        selected_template = BB_TEMPLATE_PYPI if use_pypi else BB_TEMPLATE
        output = selected_template.format(
            summary=package.summary,
            md5=package.src_md5,
            sha256=package.src_sha256,
            src_uri=package.src_uri,
            src_dir=package.src_dir,
            pypi_package=package.name,
            pypi_package_ext="\nPYPI_PACKAGE_EXT = \"" + get_file_extension(package.src_uri) + "\"" if not package.src_uri.endswith(".tar.gz") else "",
            license=package.license,
            license_file=package.license_file,
            license_md5=package.license_md5,
            homepage=package.homepage,
            author=package.author,
            author_email=package.author_email,
            build_dependencies=" ".join(
                [
                    dep
                    for dep in package.build_dependencies
                ]
            ),
            dependencies=" ".join(
                [
                    "{}-{}".format(python, package_to_bb_name(dep.name))
                    for dep in package.dependencies
                ]
            ),
            setuptools="3" if python == "python3" else "",
        )

    with open(bbfile, "w") as outfile:
        outfile.write(output)


def parse_requirements(requirements_file, follow_extras=False, default_license=None):
    packages = []

    with open(requirements_file, "r") as infile:
        for package in infile.read().split("\n"):
            package = package.strip()
            if package:
                if not (package.startswith("-e") or package.startswith(".")):
                    parts = [part.strip() for part in package.split("==")]
                    if len(parts) == 2:
                        packages += get_package_info(
                            parts[0],
                            parts[1],
                            follow_extras=follow_extras,
                            default_license=default_license,
                        )
                    elif len(parts) == 1:
                        packages += get_package_info(
                            parts[0],
                            None,
                            follow_extras=follow_extras,
                            default_license=default_license,
                        )
                    else:
                        print("    Unparsed package: {}".format(package))
                else:
                    print("    Skipping: {}".format(package))

    return packages


def write_preferred_versions(packages, outfile, python):
    versions = []
    for package in packages:
        versions.append(
            'PREFERRED_VERSION_{}-{} = "{}"'.format(
                python, package_to_bb_name(package.name), package.version
            )
        )

    with open(outfile, "w") as outfile:
        outfile.write("\n".join(versions))


def generate_recipes(packages, outdir, python, follow_extras=False, pypi=False):
    for package in packages:
        generate_recipe(package, outdir, python, use_pypi=pypi)

        if follow_extras:
            extras = [dep for dep in package.dependencies if dep.extra]
            processed = []
            for extra in extras:
                if extra.extra in processed:
                    continue

                processed.append(extra.extra)
                extra_package = package
                extra_package = extra_package._replace(
                    name=package.name + "-{}".format(extra.extra)
                )
                extra_package = extra_package._replace(
                    dependencies=[Dependency(package.name, package.version, None)]
                    + [
                        Dependency(e.name, e.version, None)
                        for e in extras
                        if e.extra == extra.extra
                    ]
                )
                generate_recipe(extra_package, outdir, python, is_extra=True, use_pypi=pypi)


def generate_oe_pypi_recipes(yocto_layers_dir, existing_packages, python_arg):
    print("Gathering recipes in Yocto layers directory: {}".format(yocto_layers_dir))
    with open(existing_packages, "w", encoding="utf-8") as outfile:
        for root, _, files in os.walk(yocto_layers_dir):
            for file in files:
                pkg_start = python_arg + '-'
                if file.startswith(pkg_start) and file.endswith(".bb"):
                    if "-" in file and "_" in file:
                        # Get the package name from file python3-webob_1.8.7.bb
                        name = file.split('_')[0].split(pkg_start)[1]
                        version = file.split('_')[1].split('.bb')[0]
                        version_array = version.split('.')
                        if len(version_array) > 1:
                            outfile.write("{}=={}\n".format(name, version))
                            continue
                    file_path = os.path.join(root, file)
                    print("Could not parse: {}".format(file_path))


def parse_existing_packages(existing_packages):
    with open(existing_packages, "r", encoding="utf-8") as infile:
        for line in infile:
            line = line.strip()
            if "==" in line:
                name = line.split("==")[0]
                version = line.split("==")[1]
            else:
                name = line
                version = None

            nope = ''
            package = Package(
                name,
                version,
                nope,nope,nope,nope,nope,nope,nope,nope,nope,nope,nope,nope,nope
            )
            PROCESSED_PACKAGES.append(package)


def main():
    try:
        parser = argparse.ArgumentParser()
        parser.add_argument("--package", "-p", help="The package to process.")
        parser.add_argument(
            "--version", "-v", help="The package version.", default=None
        )
        parser.add_argument("--requirements", "-r", help="The pypi requirements file.")
        parser.add_argument(
            "--extras", "-e", action="store_true", help="Generate recipes for extras."
        )
        parser.add_argument(
            "--outdir", "-o", help="The recipe directory.", default="./"
        )
        parser.add_argument(
            "--python",
            "-y",
            help="The python version to use.",
            default="python3",
            choices=["python", "python3"],
        )
        parser.add_argument(
            "--licenses",
            "-l",
            action="store_true",
            help="Output an updated license map upon completion.",
        )
        parser.add_argument(
            "--default-license",
            "-d",
            help="The default license to use when the package license cannot be mapped.",
            default=None,
        )
        parser.add_argument(
            "--pypi",
            "-s",
            action="store_true",
            help="Use oe pypi class for recipe"
        )
        parser.add_argument(
            "--yocto-layers-dir",
            help="Yocto layers directory",
            default=None
        )
        parser.add_argument(
            "--existing-packages",
            help="The existing packages to process in pypi requirements file.",
            default=None
        )
        parser.add_argument(
            "--write-preferred",
            action="store_true",
            help="Write preferred versions to a file.",
            default=True
        )
        args = parser.parse_args()

        if args.yocto_layers_dir and args.existing_packages:
            generate_oe_pypi_recipes(args.yocto_layers_dir, args.existing_packages, args.python)
            print("Existing packages are available in: {}".format(args.existing_packages))
            sys.exit(0)

        if args.existing_packages:
            parse_existing_packages(args.existing_packages)

        print("Gathering info:")
        packages = []
        if args.requirements:
            packages = parse_requirements(
                args.requirements,
                follow_extras=args.extras,
                default_license=args.default_license,
            )
        elif args.package:
            packages = get_package_info(
                args.package,
                args.version,
                follow_extras=args.extras,
                default_license=args.default_license,
            )
        else:
            raise Exception("No packages provided!")

        print(f"Generating recipes ({len(packages)}):")
        generate_recipes(packages, args.outdir, args.python, args.extras, args.pypi)

        print()
        if args.licenses:
            license_file = os.path.join(args.outdir, "licenses.py")
            with open(license_file, "w") as outfile:
                outfile.write("LICENSES = " + pformat(licenses.LICENSES))

            print("License mappings are available in: {}".format(license_file))

        if args.write_preferred:
            version_file = os.path.join(args.outdir, "{}-versions.inc".format(args.python))
            write_preferred_versions(packages, version_file, args.python)
            print("PREFERRED_VERSIONS are available in: {}".format(version_file))

    except Exception as e:
        print(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        os._exit(1)


if __name__ == "__main__":
    main()
