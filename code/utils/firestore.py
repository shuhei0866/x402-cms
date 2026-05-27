"""Firestore client construction shared by readers, writers, and the publisher.

Three-branch precedence — inject > project > ADC — lives here so the
rest of the codebase doesn't repeat it. Tests inject a MagicMock;
runtime uses ADC or a project kwarg passed by the server / CLI.
"""

from __future__ import annotations

from google.cloud import firestore


def build_client(
    client: firestore.Client | None = None,
    project: str | None = None,
) -> firestore.Client:
    """Return `client` if provided, else build one.

    Precedence:
    1. `client` non-None — tests inject a MagicMock, orchestrators
       thread a single instance through a chain of readers/writers.
    2. project set — `firestore.Client(project=project)`.
    3. neither — `firestore.Client()`, which picks the project from
       Application Default Credentials.
    """
    if client is not None:
        return client
    if project:
        return firestore.Client(project=project)
    return firestore.Client()
