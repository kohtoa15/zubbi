# Copyright 2018 BMW Car IT GmbH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import hashlib
import logging
import os

import yaml

from zubbi.models import ZuulTenant
from zubbi.scraper.exceptions import CheckoutError, ScraperConfigurationError


TENANTS_DIRECTORY = "tenants"

LOGGER = logging.getLogger(__name__)


class TenantParser:
    def __init__(self, scrape_time, sources_file=None, sources_repo=None):
        if sources_file:
            self.sources = self._load_tenant_sources_from_file(sources_file)
        else:
            self.sources = self._load_tenant_sources_from_repo(sources_repo)

        self.scrape_time = scrape_time
        self.repo_map = {}
        self.tenants = []

    def parse(self):
        for tenant_src in self.sources:
            source = tenant_src["tenant"]["source"]
            tenant_name = tenant_src["tenant"]["name"]
            github_source = source.get("github")
            if not github_source:
                LOGGER.debug("No key 'github' found in source, skipping ...")
                break

            uuid = hashlib.sha1(str.encode(tenant_name)).hexdigest()
            tenant = ZuulTenant(meta={"id": uuid})
            tenant.tenant_name = tenant_name
            tenant.scrape_time = self.scrape_time

            # project_type is config- or untrusted-project
            for project_type, projects in github_source.items():
                for project in projects:
                    self._update_repo_map(project, tenant_name)

            self.tenants.append(tenant)

        return self.repo_map, self.tenants

    def _update_repo_map(self, project, tenant):
        project_name, exclude = self._extract_project(project)

        # Map the current tenant to the current repository
        repo_tenant_entry = self.repo_map.setdefault(
            project_name, {"jobs": [], "roles": []}
        )

        # Update repo_tenant mapping
        if "jobs" not in exclude:
            repo_tenant_entry["jobs"].append(tenant)
        repo_tenant_entry["roles"].append(tenant)

    def _extract_project(self, project):
        project_name = project
        exclude = []
        if type(project) is dict:
            # Get the first key of the dict containing the project name.
            project_name = list(project.keys())[0]
            exclude = project.get("exclude", [])
        return project_name, exclude

    def _load_tenant_sources_from_file(self, sources_file):
        LOGGER.info("Parsing tenant sources file '%s'", sources_file)
        with open(sources_file) as f:
            sources = yaml.load(f)
        return sources

    def _load_tenant_sources_from_repo(self, sources_repo):
        LOGGER.info("Collecting tenant sources from repo '%s'", sources_repo)
        sources = []
        try:
            tenants = sources_repo.list_directory(TENANTS_DIRECTORY)
        except CheckoutError:
            raise ScraperConfigurationError(
                "Cannot load tenant sources. Repo '%s' does not contain a "
                "'tenants' folder".format(sources_repo.repo_name)
            )

        for tenant in tenants.keys():
            try:
                sources_yaml = sources_repo.check_out_file(
                    os.path.join("tenants", tenant, "sources.yaml")
                )
                settings_yaml = sources_repo.check_out_file(
                    os.path.join("tenants", tenant, "settings.yaml")
                )
                # NOTE (fschmidt): We parse both files and create the same data
                # structure like zuul does for the main.yaml file.
                tenant_sources = {
                    # Load the settings first, as they contain different keys
                    "tenant": yaml.load(settings_yaml)
                }
                # Update the tenant_sources with the sources file and wrap them
                # in a 'source' key
                tenant_sources["tenant"]["source"] = yaml.load(sources_yaml)

                sources.append(tenant_sources)
            except CheckoutError as e:
                # If a single tenant is missing the required file, we just skip it
                LOGGER.warning(
                    "Either 'settings.yaml' or 'sources.yaml' are "
                    "missing or empty in repo '%s': %s",
                    sources_repo.repo_name,
                    e,
                )
        return sources