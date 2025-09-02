#!/bin/bash
# ToolMux Hook - Educates AI agents on efficient usage

echo "🎯 ToolMux Active - 98.65% Token Efficiency Mode"
echo ""
echo "📋 Available Meta-Tools (use these, not direct tools):"
echo "   • catalog_tools - Discover all available backend tools"
echo "   • get_tool_schema(name) - Get parameters for specific tool"  
echo "   • invoke(name, args) - Execute any backend tool"
echo "   • get_tool_count - Show tool statistics by server"
echo ""
echo "🔄 Recommended Workflow:"
echo "   1. catalog_tools → See what's available"
echo "   2. get_tool_schema('tool_name') → Get parameters"
echo "   3. invoke('tool_name', {args}) → Execute the tool"
echo ""
echo "⚡ Efficiency: 4 meta-tools (1.35% tokens) vs hundreds of schemas (20% tokens)"
