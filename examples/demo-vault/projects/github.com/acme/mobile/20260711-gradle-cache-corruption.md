---
id: 20260711-gradle-cache-corruption
type: lesson
scope: project
project: github.com/acme/mobile
tags:
- gradle
- android
- build
created: '2026-07-11'
source: user_requested
status: active
confidence: medium
derived_from: []
superseded_by: null
used: 0
dead_end: 0
title: Gradle cache corruption
---
Gradle build cache corruption after force-quit produces silent stale-class bugs.

Problem: after a hard OS shutdown mid-build, the app ran fine but a rebuilt screen used code from two commits ago.
Tried: ./gradlew clean — did not touch ~/.gradle/caches; the poisoned entries survived.
Worked: rm -rf ~/.gradle/caches/build-cache-* and .gradle/ inside the project, then rebuild. Also enabled org.gradle.caching.debug=true in CI to catch cache-key collisions early.
Takeaway: 'clean' is project-local; the real cache lives in $HOME. When behavior contradicts source, nuke the shared cache before you debug the code.
