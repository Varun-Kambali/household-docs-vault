# 0001. The app runs only on my Mac
Date: 2026-11-11 · Status: accepted

## Context
The vault holds identity papers, insurance policies, medical records and card details. My other projects are deployed to free hosts so a reviewer can try them. A hosted copy of this one would mean putting a family's papers, or at best a demo of that, on someone else's machine, and the real thing could never be the thing that is hosted.

## Decision
The app is not deployed to the web or to any hosting platform. It runs on my Mac, and its data lives on the Mac's disk, with Google Drive (ADR 0002) as the one storage service. The public repo holds code and synthetic data only, and the README shows the app through a demo GIF and a quickstart that runs on a synthetic vault.

## Alternatives considered
- **A hosted demo with fake data.** Easy for a reviewer to click, but it is not the product, and it would need hosting that can run local-sized models, which the free tiers cannot.
- **A hosted app with my real data.** Ruled out by the kind of data it would hold.

## Consequences
A reviewer cannot try the app in a browser; they read the case study and the results files, watch the GIF, or run it on the synthetic vault. Models must fit the Mac. Docker on macOS cannot use the GPU, so the app runs natively and the Docker image built in CI only checks the packaging.
