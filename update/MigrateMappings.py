import sys, os, re, json, copy, shutil, glob, json
import SRGSorter
from pprint import pprint
from hashlib import md5
from zipfile import ZipFile
from collections import OrderedDict

def read_match(file, map):
    if not os.path.isfile(file):
        return
    print('Reading: ' + file)
    
    mode = -1 #0 CLASSES 1 FIELDS 2 METHODS
    lineNum = 0
    with open(file, 'r') as f:
        for line in f.readlines():
            line = line.rstrip('\n')
            lineNum += 1
            if len(line) == 0 or line[0] == '#':
                continue
            if line[0] == '[':
                if line == '[CLASSES]': mode = 0
                elif line == '[FIELDS]': mode = 1
                elif line == '[METHODS]': mode = 2
                else:
                    mode = -1
                    print('  Invalid line #%s: %s' % (lineNum, line))
            else:
                pts = line.replace('.', '/').split(' ')
                key = pts[0]
                value = pts[1]
                if mode == 2:
                    key = '%s %s' % (pts[0], pts[1])
                    value = '%s %s' % (pts[2], pts[3])
                    
                if key in map:
                    if map[key] != value:
                        print('  Conflicting Mapping Line #%s %s -> %s' % (lineNum, map[key], value))
                map[key] = value
    
def split_mtd(line):
    return [line.split(' ')[0].rsplit('/', 1)[0], line.split(' ')[0].rsplit('/', 1)[1], line.split(' ')[1]]
    
def rename_class(map, cls):
    if cls in map:
        return map[cls]
    return cls if not '$' in cls else '%s$%s' % (rename_class(map, cls.rsplit('$', 1)[0]), cls.rsplit('$', 1)[1])
    
def rename_desc(map, desc):
    return reg_desc.sub(lambda match: 'L%s;' % rename_class(map, match.group(1)), desc)

def read_extra_params(old_root, old_srg, map):
    old_ctrs = os.path.join(old_root, 'constructors.txt')
    if not os.path.exists(old_ctrs): old_ctrs = os.path.join(old_root, 'params.txt')
    warned = False
    if os.path.exists(old_ctrs):
        ctrs = {}
        with open(old_ctrs, 'r') as f:
            for line in f.readlines():
                line = line.rstrip('\n')
                if line.startswith('#'):
                    continue

                if len(line) == 0:
                    continue

                id,cls,desc,mname = None,None,None,None
                linesplit = line.split(' ')
                if len(linesplit) == 3:
                     if not warned:
                         warned = True
                         print("Not reading param names - the old format used strange prefixes because ID uniqueness was not guaranteed. Script will now generate new IDs that don't overlap with existing ones!")
                #    id,cls,desc = linesplit
                #    mname = '<init>'
                elif len(linesplit) == 4:
                    id,cls,mname,desc = linesplit
                if id == None: continue
                id = int(id)

                fulldesc = '%s %s' % (mname, desc)
                if not cls in ctrs:
                    ctrs[cls] = {}
                if fulldesc in ctrs[cls]:
                    print('  Duplicate extra param: %s %s %s %s -> %s' % (cls, mname, desc, ctrs[cls][fulldesc], id))
                ctrs[cls][fulldesc] = id

    old_srg_inverse = {}
    for type in ['CL:', 'FD:', 'MD:']:
        old_srg_inverse[type] = {}
        for ocn in old_srg[type]:
            old_srg_inverse[type][old_srg[type][ocn]] = ocn
    params = {}
    for cls in ctrs:
        new_cls = cls
        if cls in old_srg_inverse['CL:'] and old_srg_inverse['CL:'][cls] in map:
            new_obf_name = map[old_srg_inverse['CL:'][cls]]
            new_cls = srg['CL:'][new_obf_name]

        if cls.startswith('net/minecraft/') or cls.startswith('com/mojang/') and not (cls in new_classes or cls in known_classes):
            print("Class %s doesn't exist anymore, removing from params!" % cls)
        params[new_cls] = {}
        for fulldesc in ctrs[cls]:
            (name,desc) = fulldesc.split(' ')
            old_obf_desc = rename_desc(old_srg_inverse['CL:'], desc)
            old_obf_fulldesc = "%s %s" % (name, old_obf_desc)
            if old_obf_fulldesc in map:
                (new_name, new_obf_desc) = map[old_obf_fulldesc].split(' ')
                new_desc = rename_desc(srg['CL:'], new_obf_desc)
                new_fulldesc = "%s %s" % (new_name, new_desc)
                params[new_cls][new_fulldesc] = ctrs[cls][fulldesc]
                if new_cls != cls or new_fulldesc != fulldesc:
                    print("Migrated param id %d from %s %s to %s %s" %(ctrs[cls][fulldesc], cls, fulldesc, new_cls, new_fulldesc))
    return params


reg_desc = re.compile('L([^;]+);')
new_class_index = 1000
def migrate_mappings(mcp_root, old_version, new_version, output):
    files = ['forced.txt', 'class_suggestions.txt', 'field_suggestions.txt', 'method_suggestions.txt', 'new_unmapped_fixed.txt']
    #sides = ['client', 'server']
    sides = ['joined']
    map = {}
    
    ver_root = os.path.join(mcp_root, 'versions')
    old_root = os.path.join(ver_root, old_version)
    new_root = os.path.join(ver_root, new_version)
    if not os.path.exists(new_root):
        os.makedirs(new_root)
    
    #==========================================================================   
    # Read the mapping files from Depigifer, or Magidots. 
    #==========================================================================  
    migrate_root = os.path.join(output, '%s_to_%s' % (old_version, new_version))
    for side in sides:
        for file in files:
            pig = os.path.join(migrate_root, 'pig/%s_%s' % (side, file))
            magi = os.path.join(migrate_root, '%s_%s' % (side, file))
            if (os.path.isfile(pig)):
                read_match(pig, map);
            else:
                read_match(magi, map);

    if (len(map) == 0):
        print('Failed to read any mapping data!')
        return
        
    zip = ZipFile(os.path.join(output, '%s/joined_a.jar' % new_version))
    known_classes = [n[:-6] for n in zip.namelist() if n.endswith('.class') and not 'minecraftforge' in n]
    zip.close()
    
    #==========================================================================   
    # Read the old srg file, and the new obf to notch mappings.
    # Generates the inital new SRG from the matcher output and this data.
    #==========================================================================   
    from SRGSorter import load_srg_file
    old_srg = load_srg_file(os.path.join(old_root, 'joined.tsrg'))
    o_to_n = load_srg_file(os.path.join(output, '%s/joined_o_to_n.tsrg' % new_version))
    srg = {'PK:' : {}, 'CL:': {}, 'FD:': {}, 'MD:':{}}
    
    srg['PK:'] = old_srg['PK:']
    for pt in ['CL:', 'FD:', 'MD:']:
        for k,v in old_srg[pt].items():
            if k in map:
                srg[pt][map[k]] = v
    from SRGSorter import sort_srg_dict
    #sort_srg_dict(srg, 'test.srg')
    
    rg_idx_max = find_max_rg(old_srg, old_root)
    new_classes = {}
    obf_whitelist = [] # Entries that do not need to follow SRG naming, so we don't 'unfix' them below.
    params_whitelist = [] # Entries that do not get a method param id, i.e. because they override an external method like equals()
    meta = json.loads(open(os.path.join(output, '%s/joined_a_meta.json' % new_version), 'r').read())
    meta = {k:v for k,v in meta.items() if not 'minecraftforge' in k} #Remove Forge's annotations, I should filter this in MappingToy..

    err_f = open(os.path.join(migrate_root, 'migrate_errors.txt'), 'wb')

    add_new_classes(o_to_n, srg, new_classes, known_classes)

    params = read_extra_params(old_root, old_srg, map)



    fix_enums(obf_whitelist, params_whitelist, srg, meta)
    fix_method_names(obf_whitelist, srg, meta, params)
    rg_idx_max = fix_override_methods(rg_idx_max, meta, srg, err_f, obf_whitelist, o_to_n, params_whitelist, params)
    rg_idx_max = fix_unobfed_names(rg_idx_max, known_classes, new_classes, srg, o_to_n, obf_whitelist, params_whitelist, params)
    fix_inner_class_shuffle(srg)
    rg_idx_max = create_new_entries(rg_idx_max, srg, o_to_n, meta, err_f)
    
    if len(new_classes) != 0:
        with open(os.path.join(migrate_root, 'new_classes.txt'), 'wb') as f:
            for cls in sorted(new_classes.values()):
                if 'C_' in cls:
                    if not '$' in cls:
                        f.write(('%s\n' % cls).encode())
                    else:
                        try:
                            int(cls.rsplit('$', 1)[1])
                        except ValueError:
                            f.write(('%s\n' % cls).encode())
                            
    from SRGSorter import dump_tsrg
    dump_tsrg(srg, os.path.join(new_root, 'joined.tsrg'))
    new_params = os.path.join(new_root, 'params.txt')
    data = {}
    for cls,d in params.items():
        for k,v in d.items():
            if not v in data: data[v] = []
            data[v].append('%s %s' % (cls, k))
    with open(new_params, 'wb') as f:
        for id in sorted(data.keys()):
            for entry in data[id]:
                f.write(('%s %s\n' % (id, entry)).encode())
    
def find_max_rg(old_srg, old_root):
    #==========================================================================    
    # Find the highest rg id number, This is used elseware if we 
    # need to create new SRG names.
    #==========================================================================
    def max_rg(old, name):
        if not name.startswith('field_') and not name.startswith('func_'):
            return old
        new = int(name.split('_')[1])
        return old if old > new else new
    
    rg_idx_max = 0
    for k,v in old_srg['FD:'].items():
        rg_idx_max = max_rg(rg_idx_max, v.rsplit('/', 1)[1])
    for k,v in old_srg['MD:'].items():
        rg_idx_max = max_rg(rg_idx_max, v.split(' ')[0].rsplit('/', 1)[1])
        
    old_ctrs = os.path.join(old_root, 'params.txt')
    if os.path.exists(old_ctrs):
        with open(old_ctrs, 'r') as f:
            for line in f.readlines():
                line = line.rstrip('\n')
                if len(line) == 0:
                    continue
                id = int(line.split(' ')[0])
                if id > rg_idx_max:
                    rg_idx_max = id
        
    return rg_idx_max
        
def add_new_classes(o_to_n, srg, new_classes, known_classes):
    #==========================================================================
    # Add any new classes that are obfed and don't have a target name.
    # Names them C_\d++_obf
    # Done here so that RG doesn't fail on them.
    #==========================================================================
    print('Adding new classes:')
    global new_class_index
    new_class_index = 1000
    global temp
    temp = {'a': 1000,'abp': 1001,'abw': 1002,'abw$a': 1003,'acl': 1004,'ada': 1005,'ael': 1006,'afq': 1007,'agb': 1008,'aht': 1009,'ai': 1010,'ai$a': 1011,'aj': 1012,'aj$a': 1013,'akl$a': 1014,'akn$a': 1015,'alh': 1016,'ata': 1017,'ata$a': 1018,'ata$b': 1019,'ata$c': 1020,'ata$d': 1021,'ata$e': 1022,'ata$f': 1023,'ata$g': 1024,'ata$h': 1025,'ata$i': 1026,'ata$j': 1027,'ata$k': 1028,'ata$l': 1029,'ati$a': 1030,'baq': 1031,'bed': 1032,'bf': 1033,'bfo': 1034,'bjb': 1035,'bjh': 1036,'bk': 1037,'bk$a': 1038,'bks': 1039,'bks$a': 1040,'bkw': 1041,'blb': 1042,'blx': 1043,'bly': 1044,'bo': 1045,'bod': 1046,'bpa': 1047,'bqq': 1048,'bqq$a': 1049,'bqq$b': 1050,'bqq$c': 1051,'bqq$c$a': 1052,'bqq$c$b': 1053,'bru': 1054,'bwf': 1055,'bwf$a': 1056,'bwf$b': 1057,'bx': 1058,'bx$a': 1059,'bx$b': 1060,'bx$c': 1061,'bx$d': 1062,'byb': 1063,'bzp': 1064,'bzw': 1065,'ca': 1066,'caw': 1067,'caw$a': 1068,'cay': 1069,'caz$b': 1070,'cb': 1071,'cb$a': 1072,'cbb': 1073,'cbb$a': 1074,'cc': 1075,'cc$a': 1076,'cc$b': 1077,'cc$c': 1078,'cc$d': 1079,'cco': 1080,'ccp': 1081,'ccr': 1082,'cdq': 1083,'cdq$a': 1084,'cel': 1085,'cer': 1086,'cft': 1087,'cfu': 1088,'cfv': 1089,'cfw': 1090,'cfx': 1091,'cga': 1092,'cgb': 1093,'cgd': 1094,'cgf': 1095,'cgl': 1096,'cgm': 1097,'cgo': 1098,'cgo$a': 1099,'cgq': 1100,'cgw': 1101,'cgx': 1102,'cgy': 1103,'cgy$a': 1104,'cgz': 1105,'che': 1106,'chf': 1107,'chf$a': 1108,'chi': 1109,'chi$a': 1110,'chl': 1111,'chm': 1112,'chn': 1113,'cho': 1114,'chp': 1115,'chq': 1116,'cht': 1117,'chu': 1118,'chv': 1119,'chw': 1120,'chx': 1121,'chy': 1122,'chz': 1123,'cim': 1124,'cin': 1125,'cio': 1126,'cip': 1127,'ciq': 1128,'cir': 1129,'cis': 1130,'ciz': 1131,'cja': 1132,'cjz': 1133,'cka': 1134,'ckb': 1135,'ckg': 1136,'ckk': 1137,'crg': 1138,'crg$a': 1139,'crz': 1140,'csd': 1141,'csv': 1142,'csv$a': 1143,'csv$b': 1144,'cub': 1145,'cub$a': 1146,'cuq': 1147,'cuq$b': 1148,'cwz': 1149,'cxa': 1150,'cxf': 1151,'cxh$l': 1152,'cxi': 1153,'cxu$a': 1154,'cyc': 1155,'cyd$a': 1156,'cyf': 1157,'cyh': 1158,'cyi': 1159,'cyi$a': 1160,'cyl': 1161,'cyn$b$a': 1162,'cyo': 1163,'cyo$a': 1164,'d': 1165,'dbw': 1166,'dca': 1167,'dca$a': 1168,'dcw': 1169,'dcw$a': 1170,'deh$a': 1171,'dek': 1172,'dfs': 1173,'dhb': 1174,'dje$a': 1175,'djw': 1176,'dkb': 1177,'dkg': 1178,'dko': 1179,'dkp': 1180,'dll': 1181,'dlq': 1182,'dnl': 1183,'dof$d': 1184,'dof$e': 1185,'dof$f': 1186,'dof$g': 1187,'dof$h': 1188,'dof$i': 1189,'dof$m': 1190,'dqe': 1191,'dqj$a': 1192,'dql': 1193,'dqq': 1194,'dqq$a': 1195,'dqr': 1196,'dqr$a': 1197,'dqw': 1198,'dqx': 1199,'dqx$a': 1200,'dqx$b': 1201,'dqx$c': 1202,'dqx$d': 1203,'dqx$e': 1204,'dqx$f': 1205,'dqx$g': 1206,'dqx$h': 1207,'dqx$i': 1208,'dqx$j': 1209,'dqx$k': 1210,'dqx$l': 1211,'dqx$m': 1212,'dqx$n': 1213,'dqx$o': 1214,'dqx$p': 1215,'dqx$q': 1216,'dqx$r': 1217,'dqy': 1218,'dqy$a': 1219,'dqy$a$a': 1220,'dqy$b': 1221,'dqy$b$a': 1222,'dqz': 1223,'dra': 1224,'drb': 1225,'drc': 1226,'dsp': 1227,'dte$a': 1228,'dte$c$b': 1229,'dte$c$c': 1230,'dtl': 1231,'dtl$a': 1232,'dtl$b': 1233,'dtr': 1234,'dtr$a': 1235,'duk': 1236,'dwc': 1237,'dya': 1238,'dyf': 1239,'dym': 1240,'dyn': 1241,'dyr': 1242,'dzi': 1243,'dzu': 1244,'dzy': 1245,'eaa': 1246,'ead$c': 1247,'eag$a': 1248,'eag$b': 1249,'eau': 1250,'ebv': 1251,'ecj': 1252,'eck': 1253,'ecl': 1254,'fj': 1255,'id$b': 1256,'ip': 1257,'iq': 1258,'ir': 1259,'is': 1260,'it': 1261,'iv': 1262,'iw': 1263,'ix': 1264,'iy': 1265,'iz': 1266,'ja': 1267,'jc': 1268,'jd': 1269,'je': 1270,'jf': 1271,'jg': 1272,'ji': 1273,'jj': 1274,'jj$a': 1275,'jk': 1276,'jl': 1277,'jm': 1278,'jr$a': 1279,'jy$a': 1280,'kb$a': 1281,'kh$a': 1282,'kl': 1283,'km': 1284,'ku$a': 1285,'ku$b': 1286,'lk$c': 1287,'pj': 1288,'vf': 1289,'vz': 1290}
    
    def add_class(cls):
        global new_class_index
        global temp
        if cls in srg['CL:']:
            return srg['CL:'][cls]
            
        if '$' in cls:
            parent, child = cls.rsplit('$', 1)
            pobf = parent
            parent = add_class(parent)
            
            #We have to make sure the new name we are giving it doesn't collide with any existing names
            #This is only really a issue for anon inner classes but I added both branches for completeness
            if child.isdigit():
                child = int(child)
                ret = '%s$%s' % (parent, child)
                while ret in srg['CL:'].values():
                    child += 1
                    ret = '%s$%s' % (parent, child)
            else:
                if o_to_n['CL:'][cls] == cls: #Unobfed name, so the name is correct!
                    ret = cls
                elif cls in temp:
                    ret = '%s$C_%s_%s' % (parent, temp[cls], child)
                    new_class_index += 1
                else:
                    ret = '%s$C_%s_%s' % (parent, new_class_index, child)
                    new_class_index += 1
                while ret in srg['CL:'].values():
                    ret = '%s$C_%s_%s' % (parent, new_class_index, child)
                    new_class_index += 1
                    
        elif '/' in cls:
            # If we're in a package assume that package is correct but the name is wrong.
            package, name = cls.rsplit('/', 1)
            if o_to_n['CL:'][cls] == cls: #Unobfed name, so the name is correct!
                ret = cls
            elif cls in temp:
                ret = '%s/C_%s_%s' % (package, temp[cls], name)
                new_class_index += 1
            else:
                ret = '%s/C_%s_%s' % (package, new_class_index, name)
                new_class_index += 1
        elif cls in temp:
            ret = 'net/minecraft/src/C_%s_%s' % (temp[cls], cls)
            new_class_index += 1
        else:
            ret = 'net/minecraft/src/C_%s_%s' % (new_class_index, cls)
            new_class_index += 1
            
        print('  Added: %s' % ret)
        new_classes[cls] = ret
        srg['CL:'][cls] = ret
        return ret
        
    from SRGSorter import format_class
    for cls in sorted(o_to_n['CL:'], key=format_class):
        if cls in known_classes:
            add_class(cls)
            
def fix_enums(obf_whitelist, ctrs_whitelist, srg, meta):
    #==========================================================================
    # Enums encode their field names as strings in the class, so we can force
    # their names to the real ones.
    # We also fix sythetic 'bouncer' methods. To make sure they have the same
    # name as the method they bounce to. As this is how the compiler deals with
    # generic overrides.
    # We also make sure that value and valueOf dont get param names
    #==========================================================================
    print('Fixing Enum Names:')
    for cls,v in meta.items():
        if 'fields' in v:
            for obf, fld in v['fields'].items():
                if 'force' in fld:
                    force = fld['force']
                    key = '%s/%s' % (cls, obf)
                    if key in srg['FD:']:
                        old = srg['FD:'][key]
                        new = '%s/%s' % (old.rsplit('/', 1)[0], force)
                        obf_whitelist.append(new)
                        if not old == new:
                            print('  %s -> %s' % (old, force))
                            srg['FD:'][key] = new
                    else:
                        new = '%s/%s' % (srg['CL:'][key.rsplit('/', 1)[0]], force) #The class should always exist, as we *should* add it above.
                        obf_whitelist.append(new)
                        print('  %s -> %s' % (key, force))
                        srg['FD:'][key] = new
        if v['access'] & 0x4000 != 0: #is enum -- make sure values and valueOf does not get parameter names
            mcls = srg['CL:'][cls]
            valuesdesc = "values ()[L%s;" % mcls
            valueOfdesc = "valueOf (Ljava/lang/String;)L%s;" % mcls
            ctrs_whitelist.append((mcls, valuesdesc))
            ctrs_whitelist.append((mcls, valueOfdesc))

    
def fix_method_names(obf_whitelist, srg, meta, params):
    print('Fixing Method Names')
    for cls,v in meta.items():
        if 'methods' in v:
            for key,mtd in v['methods'].items():
                name,desc = key.replace('(', ' (').split(' ')
                key = '%s/%s %s' % (cls, name, desc)
                if 'force' in mtd:
                    force = mtd['force']
                    if key in srg['MD:']:
                        old = srg['MD:'][key]
                        new = '%s/%s %s' % (old.split(' ')[0].rsplit('/', 1)[0], force, old.split(' ')[1])
                        obf_whitelist.append(new)
                        if not old == new:
                            srg['MD:'][key] = new
                            print('  %s -> %s' % (old.split(' ')[0], force))
                            name = old.split(' ')[0].rsplit('/', 1)[1]
                        if old.startswith("func_"):
                            srgid = int(old.split('_')[1])
                            fulldesc = "%s %s" % (old.split(' ')[0].rsplit('/', 1)[1], rename_desc(srg['CL:'], desc))
                            if srg['CL:'][cls] not in params: params[srg['CL:'][cls]] = {}
                            params[srg['CL:'][cls]][fulldesc] = srgid
                            print("Reusing srg id %d as paramid for %s %s from old %s " % (srgid, srg['CL:'][cls], fulldesc, key))
                        else:
                            fulldesc_old = "%s %s" % (old.split(' ')[0].rsplit('/', 1)[1], rename_desc(srg['CL:'], desc))
                            fulldesc_new = "%s %s" % (force, rename_desc(srg['CL:'], desc))
                            if srg['CL:'][cls] not in params: params[srg['CL:'][cls]] = {}
                            if fulldesc_old in params[srg['CL:'][cls]]:
                                srgid = params[srg['CL:'][cls]][fulldesc_old]
                                del(params[srg['CL:'][cls]][fulldesc_old])
                                params[srg['CL:'][cls]][fulldesc_new] = srgid
                                print("Reusing srg id %d as paramid for %s %s from old %s " % (srgid, srg['CL:'][cls], fulldesc, fuldesc_old))
                    else:
                        new = '%s/%s %s' % (srg['CL:'][key.split(' ')[0].rsplit('/', 1)[0]], force, rename_desc(srg['CL:'], desc))
                        obf_whitelist.append(new)
                        print('  %s -> %s' % (key, force))
                        srg['MD:'][key] = new

def fix_unobfed_names(rg_idx_max, known_classes, new_classes, srg, o_to_n, obf_whitelist, ctrs_whitelist, ctrs):
    #==========================================================================
    #  Use the unobfed names from the class/mappings if it matches Notch names
    #  Also attempts to detect things that 'lost' their unobfed names, and 
    #  creates new SRG names for them.
    #==========================================================================
    print('Fixing unobfed names:')
    unobfed = [] #Gather all entries that are the same in notch and obf.
    obfed = [] #Entires that WERE unobfed, but now have obfed names.

    for k,v in o_to_n['CL:'].items():
        if k == v:
            unobfed.append(k)
    for k in sorted(o_to_n['FD:'], key=SRGSorter.format_field):
        v = o_to_n['FD:'][k]
        obf_cls, obf_name = k.rsplit('/', 1)
        notch_cls, notch_name = v.rsplit('/', 1)
        srg_cls, srg_name = ['', ''] if not k in srg['FD:'] else srg['FD:'][k].rsplit('/', 1)
        if obf_name == notch_name:
            unobfed.append(k)
            if obf_cls in new_classes or not k in srg['FD:'] and len(notch_name) > 1:
                srg['FD:'][k] = '%s/%s' % (rename_class(srg['CL:'], obf_cls), notch_name)
                print('  FD: NULL -> %s'  % srg['FD:'][k])
        elif k in srg['FD:'] and not srg['FD:'][k] in obf_whitelist and not srg_name.startswith('field_'):
            new_name = 'field_%s_%s_' % (rg_idx_max, obf_name)
            rg_idx_max += 1
            srg['FD:'][k] = '%s/%s' % (rename_class(srg['CL:'], obf_cls), new_name)
            print('  FD: %s/%s -> %s' % (rename_class(srg['CL:'], obf_cls), srg_name, new_name))
            
    for k in sorted(o_to_n['MD:'], key=SRGSorter.format_method):
        v = o_to_n['MD:'][k]
        obf_cls, obf_name, obf_desc = split_mtd(k)
        srg_cls, srg_name, srg_desc = [rename_class(srg['CL:'], obf_cls), '', rename_desc(srg['CL:'], obf_desc)] if not k in srg['MD:'] else split_mtd(srg['MD:'][k])
        if not obf_cls in known_classes:
            continue
        if obf_name == v.split(' ')[0].rsplit('/', 1)[1] and not 'lambda$' in obf_name and len(obf_name) > 1 and '<clinit>' != obf_name:
            unobfed.append(k)
            desc = rename_desc(srg['CL:'], obf_desc)
            fulldesc = '%s %s' % (obf_name, desc)
            mcls = rename_class(srg['CL:'], obf_cls)
            hasdesc = (mcls,fulldesc) in ctrs_whitelist or (mcls in ctrs and fulldesc in ctrs[mcls])
            old_print_behavior = (obf_cls in new_classes or not k in srg['MD:']) and not obf_name.startswith('<')
            # skip methods that are known and constructors that lack params
            if obf_cls in new_classes or not (k in srg['MD:'] and hasdesc if obf_name != '<init>' else desc == "()V" or hasdesc):
                filter = ['valueOf', 'values', 'main']
                if not mcls in ctrs:
                    ctrs[mcls] = {}
                if not fulldesc in ctrs[mcls] and (mcls, fulldesc) not in ctrs_whitelist:
                    ctrs[mcls][fulldesc] = rg_idx_max
                    rg_idx_max += 1
                if obf_name != '<init>': #constructors dont belong into the srg file for some reason
                    srg['MD:'][k] = '%s/%s %s' % (mcls, obf_name, desc)
                #remove `and old_print_behavior` once a run has been completed
                if not obf_name in filter and old_print_behavior: #Just spam, it gets lost from RG's gen.. Figure a way to force these names to be in the list?
                    print('  MD: NULL -> %s, param ID %s' % ('%s/%s %s' % (mcls, obf_name, desc), str(ctrs[mcls][fulldesc]) if fulldesc in ctrs[mcls] else "inherited"))
        elif k in srg['MD:'] and not srg['MD:'][k] in obf_whitelist and not srg_name.startswith('func_') and not srg_name.startswith('access$'): # access$ method are synthetic bridges. Dont give them a srg name.
            srgid = rg_idx_max
            desc = rename_desc(srg['CL:'], obf_desc)
            fulldesc = '%s %s' % (obf_name, desc)
            mcls = rename_class(srg['CL:'], obf_cls)
            if mcls in ctrs and fulldesc in ctrs[mcls]:
                srgid = ctrs[mcls][fulldesc]
                del(ctrs[mcls][fulldesc])
                print("Using paramid %d as srg id for %s %s %s" % (srgid, mcls, obf_name, desc))
            new_name = 'func_%s_%s_' % (srgid, obf_name)
            if srgid == rg_idx_max: rg_idx_max += 1
            print('  MD: %s -> %s' % (srg['MD:'][k], new_name))
            srg['MD:'][k] = '%s/%s %s' % (rename_class(srg['CL:'], obf_cls), new_name, srg_desc)
        elif obf_name.startswith('lambda$'): #Unobfed lambdas, they are sythetic, so we care to add srg names to rename params?
            # use param naming scheme introduced above??
            new_name = None
            old_key = '%s/NULL %s' % (srg_cls, srg_desc)
            
            if k in srg['MD:']:
                if not srg_name.startswith('func_'):
                    new_name = 'func_%s_lam_' % (rg_idx_max)
                    rg_idx_max += 1
                elif not srg_name.endswith('_lam_'):
                    new_name = 'func_%s_lam_' % (srg_name.split('_')[1])
                old_key = srg['MD:'][k]
            else:
                new_name = 'func_%s_lam_' % (rg_idx_max)
                rg_idx_max += 1
                
            if new_name != None:
                srg['MD:'][k] = '%s/%s %s' % (srg_cls, new_name, srg_desc)
                print('  MD: %s -> %s' % (old_key, new_name))
    
    renames = {}
    for k in sorted(srg['CL:'], key=SRGSorter.format_class):
        v = srg['CL:'][k]
        if k in unobfed and v != k:
            renames[v] = k
            srg['CL:'][k] = k
            print('  CL: %s -> %s' % (v, k))
    
    for k in sorted(srg['CL:'], key=SRGSorter.format_class):
        v = srg['CL:'][k]
        fixed = rename_class(renames, v)
        if v != fixed:
            renames[v] = fixed
            srg['CL:'][k] = fixed
            print('  CL: %s -> %s' % (v, fixed))
        
    for k in sorted(srg['FD:'], key=SRGSorter.format_field):
        v = srg['FD:'][k]
        n = '%s/%s' % (rename_class(renames, v.rsplit('/', 1)[0]), v.rsplit('/', 1)[1] if not k in unobfed else k.rsplit('/', 1)[1])
        if not v == n:
            print('  FD: %s -> %s' % (v, n))
            srg['FD:'][k] = n

    for k in sorted(srg['MD:'], key=SRGSorter.format_method):
        v = srg['MD:'][k]
        cls = rename_class(renames, v.split(' ')[0].rsplit('/', 1)[0])
        name = v.split(' ')[0].rsplit('/', 1)[1] if not k in unobfed else k.split(' ')[0].rsplit('/', 1)[1]
        n = '%s/%s %s' % (cls, name, rename_desc(renames, v.split(' ')[1]))
        if not v == n:
            print('  MD: %s -> %s' % (v, n))
            srg['MD:'][k] = n

    return rg_idx_max

def fix_inner_class_shuffle(srg):
    #==========================================================================
    # The obfusicator renames classes alphabetically, and doesn't care about 
    # sorting numeric names by length. So we need to fix the order of inner
    # classes:
    # Correct: 1, 2, 3, 4, 5, 6, 7, 8,  9, 10
    # Obf:     1, 3, 4, 5, 6, 7, 8, 9, 10,  2
    #==========================================================================
    print('Fixing Inner Class Shuffeling')
    inners = {}
    for k,v in srg['CL:'].items():
        if '$' in k:
            parent,child = k.rsplit('$', 1)
            if child.isdigit():
                if not parent in inners:
                    inners[parent] = []
                inners[parent].append(int(child))
                
    inners = {k:v for (k,v) in inners.items() if len(v) >= 10}
                
    for k,v in inners.items():
        inners[k] = sorted(v)
        if not len(v) == inners[k][-1]:
            print('  Missing inners? %s %s' % (k, pprint(inners[k])))
                
    renames = {}
    for k,v in inners.items():
        tmp = sorted([str(i) for i in v])
        needed = False
        for i in v:
            if not srg['CL:']['%s$%s' % (k, i)] == '%s$%s' % (srg['CL:'][k], tmp[i-1]):
                print('%s %s -> %s$%s' % (i, srg['CL:']['%s$%s' % (k, i)], srg['CL:'][k], tmp[i-1]))
                needed = True
                break
        if needed:
            for i in v:
                renames[srg['CL:']['%s$%s' % (k, i)]] = '%s$%s' % (srg['CL:'][k], tmp[i-1])
                print('  %s -> %s' % (srg['CL:']['%s$%s' % (k, i)], tmp[i-1]))
    
    if len(renames) > 0:
        for k,v in srg['CL:'].items():
            srg['CL:'][k] = rename_class(renames, v)
        for k,v in srg['FD:'].items():
            srg['FD:'][k] = '%s/%s' % (rename_class(renames, v.rsplit('/', 1)[0]), v.rsplit('/', 1)[1])
        for k,v in srg['MD:'].items():
            srg['MD:'][k] = '%s/%s %s' % (rename_class(renames, v.split(' ')[0].rsplit('/', 1)[0]), v.split(' ')[0].rsplit('/', 1)[1], rename_desc(renames, v.split(' ')[1]))

def fix_override_methods(rg_idx_max, meta, srg, err_f, obf_whitelist, o_to_n, ctrs_whitelist, ctrs):
    print('Fixing overriden methods')
    linked = OrderedDict()
    roots = OrderedDict()
    for cls_name,cls in meta.items():
        if 'methods' in cls:
            #Meta has methods listing what methods they override, lets change that to list all child methods
            for mtd_key,mtd in cls['methods'].items():
                if '<' in mtd_key: #<init>/<cinit> dont need names
                    continue
                    
                mtd_name,mtd_desc = mtd_key.replace('(', ' (').split(' ')
                if 'overrides' in mtd:
                    mkey = '%s/%s %s' % (cls_name, mtd_name, mtd_desc)
                    for ord in mtd['overrides']:
                        key = '%s%s' % (ord['name'], ord['desc'])
                        if ord['owner'] in meta:
                            omtd = meta[ord['owner']]['methods'][key]
                            if not 'children' in omtd:
                                omtd['children'] = set()
                            omtd['children'].add('%s/%s %s' % (cls_name, mtd_name, mtd_desc))
                            
                        okey = '%s/%s %s' % (ord['owner'], ord['name'], ord['desc'])
                        if not mkey in linked:
                            linked[mkey] = set()
                        linked[mkey].add(okey)
                        if not okey in linked:
                            linked[okey] = set()
                            roots[okey] = linked[okey]
                        linked[okey].add(mkey)
        
    #Fill out linked values
    for k,v in linked.items():
        for t in v:
            linked[t].add(k)
    
    #for root in roots:
    #    print('  Root: %s' % (root))
            
    #Find any methods that Mojang merged in the new version but have different names in the srg.
    for key in roots:
        owner,desc = key.split(' ')
        owner,name = owner.rsplit('/', 1)
        obfed = True
        
        ids = set()
        for child in sorted(roots[key]):
            if child in srg['MD:']:
                id = srg['MD:'][child].split(' ')[0].rsplit('/', 1)[1]
                if len(id) == 1:
                    error(err_f, 'Short: %s -> %s' % (child, id))
                    
                ids.add(id)
            else:
                obf_cls, obf_name, obf_desc = split_mtd(key)
                nmd_cls = rename_class(srg['CL:'], obf_cls)
                nmd_desc = rename_desc(srg['CL:'], obf_desc)
                fulldesc = "%s %s" % (obf_name, nmd_desc)
                if nmd_cls in ctrs and fulldesc in ctrs[nmd_cls]:
                    id = ctrs[nmd_cls][fulldesc]
                    ids.add(id)


        if key in o_to_n['MD:']:
            nname = o_to_n['MD:'][key].split(' ')[0].rsplit('/', 1)[1]
            if nname == name: #The root is unobfed
                ids = {nname}
                obfed = False
                
        if len(ids) > 1:
            error(err_f, 'Conflicting IDS: %s' % (key)) #We need to pick one and fix it
            for child in sorted(roots[key]):
                if child in srg['MD:']:
                    error(err_f, '  %s -> %s' % (child, srg['MD:'][child].split(' ')[0].rsplit('/', 1)[1]))
                else:
                    obf_cls, obf_name, obf_desc = split_mtd(key)
                    nmd_cls = rename_class(srg['CL:'], obf_cls)
                    nmd_desc = rename_desc(srg['CL:'], obf_desc)
                    fulldesc = "%s %s" % (obf_name, nmd_desc)
                    if nmd_cls in ctrs and fulldesc in ctrs[nmd_cls]:
                        error(err_f, '  %s -> Param ID %s' % (child, ctrs[nmd_cls][fulldesc]))
                    else:
                        error(err_f, '  %s -> NULL' % (child))
                    
        if not owner in meta: #Outside MC codebase, everything needs to use unobfed names
            if not owner in ctrs:
                ctrs[owner] = {}
            pfulldesc = "%s %s" % (name, desc)
            if not pfulldesc in ctrs[owner]:
                ctrs[owner][pfulldesc] = rg_idx_max
                rg_idx_max += 1
            for child in sorted(roots[key]):
                cowner,cdesc = child.split(' ')
                cowner,cname = cowner.rsplit('/', 1)
                mcls, mdesc = (rename_class(srg['CL:'], cowner), rename_desc(srg['CL:'], cdesc))
                fulldesc = "%s %s" % (name, mdesc)
                if child in srg['MD:']:
                    oowner,odesc = srg['MD:'][child].split(' ')
                    oowner,oname = oowner.rsplit('/', 1)
                    
                    new = '%s/%s %s' % (oowner, name, odesc)
                    obf_whitelist.append(new)
                    mcls = oowner
                    fulldesc = "%s %s" % (name, odesc)
                    
                    if oname != name:
                        print('  %s %s -> %s (inherited param id %d)' % (child, oname, name, ctrs[owner][pfulldesc]))
                        srg['MD:'][child] = new
                else:
                    new = '%s/%s %s' % (mcls, name, mdesc)
                    obf_whitelist.append(new)
                    
                    print('  %s NULL -> %s (inherited param id %d)' % (child, name, ctrs[owner][pfulldesc]))
                    srg['MD:'][child] = new
                ctrs_whitelist.append((mcls, fulldesc))

        else:
            new_name = None
            if len(ids) == 1:
                new_name = ids.pop()
            elif len(ids) == 0:
                new_name = 'func_%s_%s_' % (rg_idx_max, name)
                rg_idx_max += 1
            else: # Existing methods got merged, make a new name
                new_name = 'func_%s_%s_' % (rg_idx_max, name)
                rg_idx_max += 1
                error(err_f, 'Failed to find ID: %s -> %s %s' % (key, new_name, sorted(ids)))

            if not new_name is None: #can this even happen?
                paramid = None
                if key in srg['MD:']:
                    oowner,odesc = srg['MD:'][key].split(' ')
                    oowner,oname = oowner.rsplit('/', 1)
                    
                    new = '%s/%s %s' % (oowner, new_name, odesc)
                    if not obfed:
                        obf_whitelist.append(new)
                        if not oowner in ctrs:
                            ctrs[oowner] = {}
                        fulldesc = "%s %s" % (new_name, odesc)
                        if not fulldesc in ctrs[oowner]:
                            paramid = rg_idx_max
                            ctrs[oowner][fulldesc] = paramid
                            rg_idx_max += 1
                        else: paramid = ctrs[oowner][fulldesc]
                        
                    if oname != new_name:
                        if paramid == None:
                            print('  %s %s -> %s' % (key, oname, new_name))
                        else:
                            print('  %s %s -> %s (param id %d)' % (key, oname, new_name, paramid))
                        srg['MD:'][key] = new
                else:
                    mcls, mdesc = (rename_class(srg['CL:'], owner), rename_desc(srg['CL:'], desc))
                    new = '%s/%s %s' % (mcls, new_name, mdesc)
                    if not obfed:
                        obf_whitelist.append(new)
                        if not mcls in ctrs:
                            ctrs[mcls] = {}
                        fulldesc = "%s %s" % (new_name, mdesc)
                        if not fulldesc in ctrs[mcls]:
                            paramid = rg_idx_max
                            ctrs[mcls][fulldesc] = paramid
                            rg_idx_max += 1
                        else: paramid = ctrs[mcls][fulldesc]
                        print('  %s NULL -> %s (param %d)' % (key, new_name, paramid))
                    else:
                        print('  %s NULL -> %s' % (key, new_name))
                    srg['MD:'][key] = new
                    
                for child in sorted(roots[key]):
                    cowner,cdesc = child.split(' ')
                    cowner,cname = cowner.rsplit('/', 1)
                    if child in srg['MD:']:
                        oowner,odesc = srg['MD:'][child].split(' ')
                        oowner,oname = oowner.rsplit('/', 1)
                        
                        new = '%s/%s %s' % (oowner, new_name, odesc)

                        if not obfed:
                            obf_whitelist.append(new)
                            fulldesc = "%s %s" % (new_name, odesc)
                            ctrs_whitelist.append((oowner, fulldesc))
                            
                        if oname != new_name:
                            if paramid == None:
                                print('  %s %s -> %s' % (child, oname, new_name))
                            else:
                                print('  %s %s -> %s (inherited param id %d)' % (child, oname, new_name, paramid))
                            srg['MD:'][child] = new
                    else:
                        new = '%s/%s %s' % (rename_class(srg['CL:'], cowner), new_name, rename_desc(srg['CL:'], cdesc))
                        cmcls, cmdesc = (rename_class(srg['CL:'], cowner), rename_desc(srg['CL:'], cdesc))
                        new = '%s/%s %s' % (cmcls, new_name, cmdesc)

                        if not obfed:
                            obf_whitelist.append(new)
                            fulldesc = "%s %s" % (new_name, cmdesc)
                            ctrs_whitelist.append((cmcls, fulldesc))
                            print('  %s NULL -> %s (inherited param id %d)' % (child, new_name, paramid))
                        else:
                            print('  %s NULL -> %s' % (child, new_name))
                        srg['MD:'][child] = new
                    
    return rg_idx_max

def create_new_entries(rg_idx_max, srg, o_to_n, meta, err_f):
    print('Injecting new SRG names')
       
    for owner,cls in meta.items():
        if 'fields' in cls:
            for name,fld in cls['fields'].items():
                key = '%s/%s' % (owner, name)
                if not key in srg['FD:']:
                    new_name = 'field_%s_%s_' % (rg_idx_max, name)
                    rg_idx_max += 1
                    print('  FD: %s -> %s' % (key, new_name))
                    srg['FD:'][key] = '%s/%s' % (rename_class(srg['CL:'], owner), new_name)
        if 'methods' in cls:
            for name,mtd in cls['methods'].items():
                if '<' in name: #<init>/<cinit> dont need names
                    continue
                    
                name,desc = name.replace('(', ' (').split(' ')
                key = '%s/%s %s' % (owner, name, desc)
                if not key in srg['MD:']:
                    new_name = 'func_%s_%s_' % (rg_idx_max, name)
                    rg_idx_max += 1
                    print('  MD: %s -> %s' % (key, new_name))
                    srg['MD:'][key] = '%s/%s %s' % (rename_class(srg['CL:'], owner), new_name, rename_desc(srg['CL:'], desc))
                    if len(name) > 2:
                        error('Long Name: %s -> %s' % (key, new_name))
    return rg_idx_max

def purge(dir, pattern):
    for f in os.listdir(dir):
        if re.search(pattern, f):
            os.remove(os.path.join(dir, f))
            
def getMinecraftPath():
    if   sys.platform.startswith('linux'):
        return os.path.expanduser("~/.minecraft")
    elif sys.platform.startswith('win'):
        return os.path.join(os.getenv("APPDATA"), ".minecraft")
    elif sys.platform.startswith('darwin'):
        return os.path.expanduser("~/Library/Application Support/minecraft")
    else:
        print('Cannot detect of version : %s. Please report to your closest sysadmin' % sys.platform)
        sys.exit()
        
def error(err_f, line):
    print('  %s' % (line))
    err_f.write(('%s\n' % (line)).encode())
    
if __name__ == '__main__':
    if (len(sys.argv) < 4):
        print('Usage: py MigradeMappings.py <MCPConfig> <OLD_VERSON> <NEW_VERSION> <ToyData>')
    elif (len(sys.argv) == 5):
        migrate_mappings(os.path.join('.', sys.argv[1]), sys.argv[2], sys.argv[3], os.path.join('.', sys.argv[4]))
    else:
        migrate_mappings(os.path.join('.', sys.argv[1]), sys.argv[2], sys.argv[3], 'output')