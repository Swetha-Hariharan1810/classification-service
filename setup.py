from pathlib import Path

from setuptools import find_packages, setup

# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! #
# NOTE: REMEMBER TO UPDATE THE FALLBACK VERSION IN class_service/__init__.py WHEN RELEASING #
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!! #
MAJOR_VERSION = 1
MINOR_VERSION = 2
PATCH_VERSION = 0
IS_DEV_VERSION = True


install_requires = list(
    filter(
        lambda x: not x.startswith("--"),
        open("requirements.txt").read().splitlines(),
    )
)


tests_requires = ["pandas", "pytest"]

project_root = Path(__file__).parent


def discover_version() -> str:
    version = f"{MAJOR_VERSION}.{MINOR_VERSION}.{PATCH_VERSION}"

    return version


CUR_VERSION = discover_version()


all_requires = sorted(
    install_requires + tests_requires + ["jupyterlab", "matplotlib"]
)
setup(
    name="class_service",
    version=CUR_VERSION,
    python_requires=">=3.7.0",
    description="Birch classification service",
    author="Birch Technology",
    long_description=(project_root / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    package_dir={"": "src"},
    packages=find_packages(where="src", include=["class_service*"]),
    package_data={"class_service": ["*.json"]},
    install_requires=install_requires,
    extras_require={"tests": tests_requires, "all": all_requires},
)
