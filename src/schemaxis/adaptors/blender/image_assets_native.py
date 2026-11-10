"""Single-file image interpretation and admission before material evaluation."""
import hashlib
import bpy
from schemaxis.artifacts import file_digest
from schemaxis.errors import fail
from .image_assets import ALPHA,dimensions,MAX_TOTAL_PIXELS


def admit(image,total=0):
    if (image.source!='FILE' or image.type!='IMAGE' or image.is_multiview
            or image.use_multiview or len(image.packed_files)>1
            or len(image.tiles)!=1 or image.tiles[0].number!=1001):
        fail('UNSUPPORTED_RESOURCE','image needs a single-file, single-view captured resource',image.name)
    total+=dimensions(*image.size,image.name)
    if total>MAX_TOTAL_PIXELS:
        fail('RESOURCE_BUDGET_EXCEEDED','production images exceed 16777216 aggregate pixels',image.name)
    return total


def configure(image,spec,total=0):
    total=admit(image,total)
    image.colorspace_settings.name=spec['colourSpace'];image.alpha_mode=ALPHA[spec['alphaMode']]
    # Preserve the fixed baseline's image-cache policy; authored precision/cache
    # selection needs its own resource and numerical qualification.
    image.use_half_precision=True
    if spec['pack']:image.pack()
    return total


def observe(image):
    if getattr(image,'animation_data',None) or image.is_dirty or not image.use_half_precision or not image.use_fake_user:
        fail('VERIFICATION_FAILED','captured image interpretation or unsaved pixels changed',image.name)
    mode=next((key for key,value in ALPHA.items() if value==image.alpha_mode),None)
    if mode is None:fail('VERIFICATION_FAILED','image alpha interpretation is undeclared',image.name)
    packed=bool(image.packed_file)
    digest=hashlib.sha256(bytes(image.packed_file.data)).hexdigest() if packed else file_digest(bpy.path.abspath(image.filepath))
    return {'id':image.name,'sha256':digest,'colourSpace':image.colorspace_settings.name,'pack':packed,'alphaMode':mode}
