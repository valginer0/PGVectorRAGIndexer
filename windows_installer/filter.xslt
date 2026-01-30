<?xml version="1.0" encoding="utf-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:wix="http://schemas.microsoft.com/wix/2006/wi">

    <xsl:output method="xml" indent="yes" />

    <!-- Identity transform: copy everything by default -->
    <xsl:template match="@*|node()">
        <xsl:copy>
            <xsl:apply-templates select="@*|node()" />
        </xsl:copy>
    </xsl:template>

    <!-- Match the Component that contains the Main Exe and suppress it -->
    <!-- We match any Component that has a File child with Source ending in PGVectorRAGIndexer-Setup.exe -->
    <xsl:template match="wix:Component[wix:File[contains(@Source, 'PGVectorRAGIndexer-Setup.exe')]]" />

</xsl:stylesheet>
