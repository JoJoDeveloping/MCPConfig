#!/bin/bash

if ! sha256sum --check - <<EOF
090cfc1039348fee50bd157ed6398ab99a0ddaaa2086d97af3db5856512e772c  auto_update.bat
EOF
then
  echo "Error: The original auto_update.bat has changed, please adapt this script, too!"
  exit 1
fi
# Requires python3+, and python wget installed https://pypi.org/project/wget/

# Update these as nessasary
MAP_TOY=1.0.6
DEPIG=1.0.4

#REM Basic paths, shouldn't need changing
MC_ROOT=~/.minecraft
MCP_CONFIG=..
MAP_DATA=output
BIN_DIR=bin

# Read arguments
OLD_VERSION=$1
NEW_VERSION=$2

MIGRATE_DIR="${MAP_DATA}/${OLD_VERSION}_to_${NEW_VERSION}"

echo Starting $OLD_VERSION -\> $NEW_VERSION
echo MC Root : $MC_ROOT
echo MCP Cfg : $MCP_CONFIG
echo Data    : $MAP_DATA
echo Bin     : $BIN_DIR
echo Migrate : $MIGRATE_DIR
echo ""

if [ ! -d $BIN_DIR ]; then
    mkdir $BIN_DIR
fi

MAP_TOY_FILE="${BIN_DIR}/MappingToy-${MAP_TOY}-all.jar"
if [ ! -f $MAP_TOY_FILE ]; then
    echo Downloading Mapping Toy: $MAP_TOY
    curl -o  "${MAP_TOY_FILE}" "https://files.minecraftforge.net/maven/net/minecraftforge/lex/MappingToy/$MAP_TOY/MappingToy-$MAP_TOY-all.jar"
    echo ""
fi

if [ ! -f $MAP_TOY_FILE ]; then
  exit 0
fi

java -jar $MAP_TOY_FILE --libs --output $MAP_DATA/ --mc $MC_ROOT/ --version $OLD_VERSION --version $NEW_VERSION

OLD_MAP=$MAP_DATA/$OLD_VERSION/client.txt
if [ ! -f $OLD_MAP ]; then
    echo Missing Old Map: $OLD_MAP
    exit 0
fi
echo Old Map : $OLD_MAP
NEW_MAP=$MAP_DATA/$NEW_VERSION/client.txt
if [ ! -f $NEW_MAP ]; then
    echo Missing New Map: $NEW_MAP
    exit 0
fi
echo New Map : $NEW_MAP
echo ""

# rm -rf old
# echo Extracting: mcps\%OLD_VERSION%.zip -^> old
# unzip -q mcps\%OLD_VERSION%.zip -d old
# mkdir old\jars\versions\%OLD_VERSION%\
# copy output\%OLD_VERSION%\joined_a.jar old\jars\versions\%OLD_VERSION%\%OLD_VERSION%_joined.jar

# pushd old
#   py runtime\decompile.py --joined -p -a -n
# popd

# rm -rf new
# echo Extracting: mcps\%OLD_VERSION%.zip -^> new
# unzip -q mcps\%OLD_VERSION%.zip -d new
# py %SCRIPTS%\UpdateClasspath.py %NEW_VERSION% new

DEPIG_FILE=$BIN_DIR/MappingToy-$DEPIG-fatjar.jar
if [ ! -f $DEPIG_FILE ]; then
    echo Downloading Depigifier: $DEPIG
    curl -o "$DEPIG_FILE" "https://files.minecraftforge.net/maven/net/minecraftforge/depigifier/$DEPIG/depigifier-$DEPIG-fatjar.jar"
    echo ""
fi
if [ ! -f $DEPIG_FILE ]; then
  exit 0
fi

echo Running First Depigifer
java -jar $DEPIG_FILE --oldPG $OLD_MAP --newPG $NEW_MAP --out $MIGRATE_DIR/pig/

echo Fix any suggestions before pressing enter
read -p "Press enter to continue"

# Re-run depigifier with any manually matches classes.
MANUAL_MATCHES=$MIGRATE_DIR/manual_classes.txt
if [ -f $MANUAL_MATCHES ]; then
    echo Running Second Depigifer
    java -jar $DEPIG_FILE --oldPG $OLD_MAP --newPG $NEW_MAP --out $MIGRATE_DIR/pig/ --mapping %MANUAL_MATCHES%
    echo ""
fi

echo Making output
# Make new MCPConfig folder and copy from previous version.
if [ ! -d $MCP_CONFIG/versions/$NEW_VERSION/ ]; then
    mkdir $MCP_CONFIG/versions/$NEW_VERSION/
fi
cp $MCP_CONFIG/versions/$OLD_VERSION/config.json $MCP_CONFIG/versions/$NEW_VERSION/config.json
cp $MCP_CONFIG/versions/$OLD_VERSION/suffixes.txt $MCP_CONFIG/versions/$NEW_VERSION/suffixes.txt
echo ""

echo Migrating
echo MigrateMappings.py $MCP_CONFIG $OLD_VERSION $NEW_VERSION $MAP_DATA
python3 MigrateMappings.py $MCP_CONFIG $OLD_VERSION $NEW_VERSION $MAP_DATA
#2>&1 1>$MIGRATE_DIR/migrate.log

# Copy over the new data
# copy /Y new\conf\joined.tsrg %MCP_CONFIG%\versions\%NEW_VERSION%\joined.tsrg
# copy /Y new\conf\constructors.txt %MCP_CONFIG%\versions\%NEW_VERSION%\constructors.txt
NEW_CLASSES=$MIGRATE_DIR/new_classes.txt
if [ -f $NEW_CLASSES ]; then
    echo Base Version: $OLD_VERSION >> $NEW_CLASSES
    cp $NEW_CLASSES $MCP_CONFIG/versions/$NEW_VERSION/SNAPSHOT.txt
fi

# pushd new
#     call py runtime\decompile.py --joined -p -a -n --rg
# popd

# py %SCRIPTS%\PostGeneration.py new >new_classes.txt

# Decompile with SpecialSource, as RG has some naming/generic artifacts that make diffing difficult.
# pushd new
#     call py runtime\cleanup.py -f
#     call py runtime\decompile.py --joined -p -a -n
# popd