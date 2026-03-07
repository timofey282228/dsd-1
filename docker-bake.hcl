variable "PYTHON_TAG" {
    default = "3.14-slim-trixie"
}

group "default" {
    targets = [ "uv", "counter", "logging", "facade" ]
}

target "uv" {
    dockerfile = "Dockerfile"
    target = "uv"
    context = null
    tags = [ "uv" ]
    args = {
        "PYTHON_TAG" = PYTHON_TAG
    }
}

target "logging" {
    dockerfile = "Dockerfile"
    target = "logging"
    context = "."
    tags = ["logging"]
    args = {
        "PYTHON_TAG" = PYTHON_TAG
    }
}

target "counter" {
    dockerfile = "Dockerfile"
    target = "counter"
    context = "."
    tags = ["counter"]
    args = {
        "PYTHON_TAG" = PYTHON_TAG
    }
}

target "facade" {
    dockerfile = "Dockerfile"
    target = "facade"
    context = "."
    tags = ["facade"]
    args = {
        "PYTHON_TAG" = PYTHON_TAG
    }
}
