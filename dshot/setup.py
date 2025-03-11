from setuptools import setup, Extension

module = Extension(
    'dshot',
    sources=[
        'dshotmodule.c',
        'motor-dshot-smi.c',
        'rpi_dma_utils.c'
    ],
    extra_compile_args=['-Wall', '-pthread'],
    extra_link_args=['-pthread']
)

setup(
    name='dshot',
    version='0.1',
    description='DSHOT protocol implementation for Raspberry Pi using SMI and DMA',
    ext_modules=[module],
)
