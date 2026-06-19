# frozen_string_literal: true

# Wrap rendered markdown tables so horizontal scroll does not break column alignment.
Jekyll::Hooks.register [:posts, :pages, :documents], :post_render do |doc|
  output = doc.output
  next if output.nil? || !output.include?("<table")

  doc.output = output
    .gsub(/<table(\s[^>]*)?>/, '<div class="table-scroll"><table\1>')
    .gsub("</table>", "</table></div>")
end
