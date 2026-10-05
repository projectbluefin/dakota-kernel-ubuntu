set shell := ["bash", "-eu", "-o", "pipefail", "-c"]

bst_image := "registry.gitlab.com/freedesktop-sdk/infrastructure/freedesktop-sdk-docker-images/bst2@sha256:d147af45a82104518bf1433b6043edd4aaf5f979bd6cd438099f8b9ff772d883"

# Runs on the GHA runner; consumers only need BuildStream's docker source.
bst *args:
    mkdir -p "${HOME}/.cache/buildstream"
    sudo podman run --rm --privileged --device /dev/fuse --network=host \
        --env BUILDBOX_STAGER=copy-or-link \
        -v "{{justfile_directory()}}:/src:rw" \
        -v "${HOME}/.cache/buildstream:/root/.cache/buildstream:rw" \
        -w /src "{{bst_image}}" \
        bash -c 'bst --no-interactive "$@"' -- ${BST_FLAGS:-} {{args}}

build:
    just bst build kernel-image.bst
    just bst artifact checkout --deps none --force kernel-image.bst --directory /src/oci

# Update source pins from Ubuntu's release feed and published generic kernel.
track-ubuntu:
    python3 .github/scripts/track_ubuntu_release.py
