"""Docker response projections consumed by the Unix sandbox adapter."""

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from eylo.sockets.sandbox.schemas import SandboxError

DOCKER_PROVIDER = "docker"


class DockerResponse(BaseModel):
    """Validate consumed fields; tolerate additional Docker response fields."""

    model_config = ConfigDict(
        frozen=True, strict=True, extra="ignore", hide_input_in_errors=True
    )

    @classmethod
    def parse(cls, value: object) -> Self:
        """Refuse malformed vendor evidence without exposing response content."""
        try:
            return cls.model_validate(value)
        except ValidationError as error:
            raise SandboxError(
                "Docker returned invalid response evidence.", vendor=DOCKER_PROVIDER
            ) from error


class DockerExecutionCreated(DockerResponse):
    execution_id: str = Field(alias="Id", min_length=1)


class DockerExecutionInspection(DockerResponse):
    running: bool = Field(alias="Running")
    exit_code: int | None = Field(alias="ExitCode")


class DockerHostConfig(DockerResponse):
    network_mode: str = Field(alias="NetworkMode")
    read_only_root: bool = Field(alias="ReadonlyRootfs")
    privileged: bool = Field(alias="Privileged")
    cap_drop: list[str] | None = Field(alias="CapDrop")
    tmpfs: dict[str, str] | None = Field(alias="Tmpfs")


class DockerContainerPolicy(DockerResponse):
    host_config: DockerHostConfig = Field(alias="HostConfig")


class DockerContainerState(DockerResponse):
    status: str = Field(alias="Status", min_length=1)


class DockerContainerInspection(DockerResponse):
    state: DockerContainerState = Field(alias="State")


class DockerServerVersion(DockerResponse):
    version: str = Field(alias="Version", min_length=1)
