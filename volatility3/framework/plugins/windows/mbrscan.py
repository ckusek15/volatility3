# This file is Copyright 2022 Volatility Foundation and licensed under the Volatility Software License 1.0
# which is available at https://www.volatilityfoundation.org/license/vsl-v1.0
#

import logging
import hashlib

from volatility3.framework import constants, interfaces, renderers, symbols
from volatility3.framework.configuration import requirements
from volatility3.framework.layers import scanners
from volatility3.framework.renderers import format_hints
from volatility3.framework.symbols import intermed
from volatility3.framework.symbols.windows.extensions import mbr

vollog = logging.getLogger(__name__)

class MBRScan(interfaces.plugins.PluginInterface):
    """ Scans for and parses potential Master Boot Records (MBRs) """

    _required_framework_version = (2, 0, 1)
    _version = (1, 0, 0)

    @classmethod
    def get_requirements(cls):
        return [
            requirements.ModuleRequirement(name = 'kernel', description = 'Windows kernel',
                                           architectures = ["Intel32", "Intel64"])            
        ]

    def _generator(self):
        kernel = self.context.modules[self.config['kernel']]
        physical_layer_name = self.context.layers[kernel.layer_name].config.get('memory_layer', None)
        
        layer = self.context.layers[physical_layer_name]
        architecture = "intel" if not symbols.symbol_table_is_64bit(self.context, kernel.symbol_table_name) else "intel64"

        symbol_table = intermed.IntermediateSymbolTable.create(context = self.context,
                                                               config_path = self.config_path,
                                                               sub_path = "windows",
                                                               filename = "mbr",
                                                               class_types = {
                                                                'PARTITION_TABLE': mbr.PARTITION_TABLE,
                                                                'PARTITION_ENTRY': mbr.PARTITION_ENTRY
                                                               })

        partition_table_object = symbol_table + constants.BANG + "PARTITION_TABLE"
        
        mbr_signature = b"\x55\xAA"
        mbr_length = 0x200
        boot_code_length = 0x1B8

        for offset, _value in layer.scan(context = self.context, scanner = scanners.MultiStringScanner(patterns = [mbr_signature])):
            mbr_start_offset = offset - (mbr_length - len(mbr_signature))
            partition_table = self.context.object(partition_table_object, offset = mbr_start_offset, layer_name = layer.name)

            full_mbr = layer.read(mbr_start_offset, mbr_length, pad = True)
            boot_code = full_mbr[:boot_code_length]
            
            if boot_code:
                all_zeros = boot_code.count(b"\x00") == len(boot_code)

            if not all_zeros:
                bootcode_hash = hashlib.md5(boot_code).hexdigest()
                full_bootcode_hash = hashlib.md5(full_mbr).hexdigest()

                partition_entries = [ partition_table.FirstEntry, partition_table.SecondEntry,
                                        partition_table.ThirdEntry, partition_table.FourthEntry ]
                partition_info = ""

                for index, partition_entry_object in enumerate(partition_entries):
                    partition_entry_object.set_index(index)
                    partition_info += str(partition_entry_object)
                
                yield 0, (
                        format_hints.Hex(offset),
                        partition_table.get_disk_signature(),
                        bootcode_hash,
                        full_bootcode_hash,
                        partition_info,
                        interfaces.renderers.Disassembly(boot_code, 0, architecture),
                        format_hints.HexBytes(boot_code)
                )
            else:
                vollog.log(constants.LOGLEVEL_VV, f"Not a valid MBR: Data all zeroed out : {format_hints.Hex(offset)}")

    def run(self):
        return renderers.TreeGrid([
            ("Potential MBR at Physical Offset", format_hints.Hex),
            ("Disk Signature", str),
            ("Bootcode md5", str),
            ("Bootcode (FULL) md5", str),
            ("Partition Entries Info", str),
            ("Disasm", interfaces.renderers.Disassembly),
            ("Hexdump", format_hints.HexBytes)
        ], self._generator())
