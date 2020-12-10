![Build Status](https://github.com/flamingo-run/flamingo/workflows/Github%20CI/badge.svg)
[![Maintainability](https://api.codeclimate.com/v1/badges/50d9f44092cbc7ee4308/maintainability)](https://codeclimate.com/github/flamingo-run/flamingo/maintainability)
[![Test Coverage](https://api.codeclimate.com/v1/badges/50d9f44092cbc7ee4308/test_coverage)](https://codeclimate.com/github/flamingo-run/flamingo/test_coverage)
[![python](https://img.shields.io/badge/python-3.8-blue.svg)](https://www.python.org/)

# Flamingo

[![Run on Google Cloud](https://deploy.cloud.run/button.svg)](https://deploy.cloud.run)


# Setup

- Create a service account for Flamingo: he's your new DevOps.
- Add this account email to all the projects you want Flamingo to manage:
   - `Cloud Build Editor`
   - `Cloud SQL Admin`
   - `Container Registry Service Agent`
   - `Service Account Admin`
   - `Service Account User`
   - `Project IAM Admin`
   - `Cloud Run Admin`
   - `Secret Manager Admin`
   - `Source Repository Administrator`
   - `Storage Admin`
   - `Cloud Datastore Admin`
- Deploy Flamingo as the service account create previously
- [Enable Firestore](https://console.cloud.google.com/firestore/data) using Datastore mode in Flamingo's project
 
