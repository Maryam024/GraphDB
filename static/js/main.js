document.addEventListener('DOMContentLoaded', function() {
    // Initialize Feather icons
    feather.replace();
    
    // DOM elements
    const queryInput = document.getElementById('query-input');
    const executeBtn = document.getElementById('execute-btn');
    const clearBtn = document.getElementById('clear-btn');
    const saveBtn = document.getElementById('save-btn');
    const loadBtn = document.getElementById('load-btn');
    const loadExamplesBtn = document.getElementById('load-examples-btn');
    const resultsContainer = document.getElementById('results-container');
    const graphContainer = document.getElementById('graph-container');
    
    // Bootstrap modals
    const examplesModal = new bootstrap.Modal(document.getElementById('examples-modal'));
    const saveModal = new bootstrap.Modal(document.getElementById('save-modal'));
    const loadModal = new bootstrap.Modal(document.getElementById('load-modal'));
    
    // Modal buttons
    const confirmSaveBtn = document.getElementById('confirm-save-btn');
    const confirmLoadBtn = document.getElementById('confirm-load-btn');
    const examplesList = document.getElementById('examples-list');
    
    // Execute query
    executeBtn.addEventListener('click', function() {
        const query = queryInput.value.trim();
        if (!query) {
            showError('Please enter a query');
            return;
        }
        
        showQueryBox(query);
        executeQuery(query);
    });
    
    // Clear query and results
    clearBtn.addEventListener('click', function() {
        queryInput.value = '';
        resetResults();
    });
    
    // Load example queries
    loadExamplesBtn.addEventListener('click', function() {
        fetch('/example_queries')
            .then(response => response.json())
            .then(data => {
                examplesList.innerHTML = '';
                
                data.examples.forEach(query => {
                    const item = document.createElement('button');
                    item.className = 'list-group-item list-group-item-action example-query';
                    item.textContent = query;
                    
                    item.addEventListener('click', function() {
                        queryInput.value = query;
                        examplesModal.hide();
                    });
                    
                    examplesList.appendChild(item);
                });
                
                examplesModal.show();
            })
            .catch(error => {
                console.error('Error loading examples:', error);
                showError('Failed to load example queries');
            });
    });
    
    // Save database
    saveBtn.addEventListener('click', function() {
        saveModal.show();
    });
    
    confirmSaveBtn.addEventListener('click', function() {
        const filename = document.getElementById('save-filename').value.trim();
        if (!filename) {
            alert('Please enter a filename');
            return;
        }
        
        fetch('/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ filename })
        })
        .then(response => response.json())
        .then(data => {
            saveModal.hide();
            if (data.error) {
                showError(data.error);
            } else {
                showSuccess(data.message);
            }
        })
        .catch(error => {
            saveModal.hide();
            console.error('Error saving database:', error);
            showError('Failed to save database');
        });
    });
    
    // Load database
    loadBtn.addEventListener('click', function() {
        loadModal.show();
    });
    
    confirmLoadBtn.addEventListener('click', function() {
        const filename = document.getElementById('load-filename').value.trim();
        if (!filename) {
            alert('Please enter a filename');
            return;
        }
        
        fetch('/load', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ filename })
        })
        .then(response => response.json())
        .then(data => {
            loadModal.hide();
            if (data.error) {
                showError(data.error);
            } else {
                showSuccess(data.message);
                // Execute a simple query to show the loaded data
                executeQuery('MATCH (n) RETURN n LIMIT 10');
            }
        })
        .catch(error => {
            loadModal.hide();
            console.error('Error loading database:', error);
            showError('Failed to load database');
        });
    });
    
    // Function to execute a query and display results
    function executeQuery(query) {
        fetch('/execute', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ query })
        })
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showError(data.error);
            } else {
                showResults(data.result, query);
                if (isDisplayQuery(query)) {
                    visualizeGraph(data.result);
                }
            }
        })
        .catch(error => {
            console.error('Error executing query:', error);
            showError('Failed to execute query');
        });
    }
    
    // Check if the query is a display query (MATCH/RETURN)
    function isDisplayQuery(query) {
        return query.toUpperCase().includes('MATCH') && query.toUpperCase().includes('RETURN');
    }
    
    // Show query box
    function showQueryBox(query) {
        const queryBox = document.createElement('div');
        queryBox.className = 'query-box';
        queryBox.textContent = query;
        
        // Clear previous results
        resetResults();
        
        resultsContainer.appendChild(queryBox);
    }
    
    // Display error message
    function showError(message) {
        const errorBox = document.createElement('div');
        errorBox.className = 'message-box message-error';
        errorBox.innerHTML = `<i data-feather="alert-triangle" class="me-2"></i> ${message}`;
        resultsContainer.appendChild(errorBox);
        feather.replace();
    }
    
    // Display success message
    function showSuccess(message) {
        const successBox = document.createElement('div');
        successBox.className = 'message-box message-success';
        successBox.innerHTML = `<i data-feather="check-circle" class="me-2"></i> ${message}`;
        resultsContainer.appendChild(successBox);
        feather.replace();
    }
    
    // Reset results container
    function resetResults() {
        resultsContainer.innerHTML = '';
    }
    
    // Display query results
    function showResults(results, query) {
        // Handle different result types
        if (Array.isArray(results)) {
            if (results.length === 0) {
                const emptyResults = document.createElement('div');
                emptyResults.className = 'message-box message-info';
                emptyResults.innerHTML = `<i data-feather="info" class="me-2"></i> No results found`;
                resultsContainer.appendChild(emptyResults);
                feather.replace();
                return;
            }
            
            // Create table for results
            const tableContainer = document.createElement('div');
            tableContainer.className = 'results-table';
            
            const table = document.createElement('table');
            table.className = 'table table-sm table-hover';
            
            // Create table header
            const thead = document.createElement('thead');
            const headerRow = document.createElement('tr');
            
            const keys = Object.keys(results[0]);
            keys.forEach(key => {
                const th = document.createElement('th');
                th.textContent = key;
                headerRow.appendChild(th);
            });
            
            thead.appendChild(headerRow);
            table.appendChild(thead);
            
            // Create table body
            const tbody = document.createElement('tbody');
            
            results.forEach(result => {
                const row = document.createElement('tr');
                
                keys.forEach(key => {
                    const td = document.createElement('td');
                    const value = result[key];
                    
                    if (value === null || value === undefined) {
                        td.textContent = 'null';
                        td.className = 'text-muted';
                    } else if (typeof value === 'object') {
                        if (value.labels) {
                            // It's a node
                            const nodePre = document.createElement('pre');
                            const labelStr = value.labels.join(':');
                            const propsStr = JSON.stringify(value.properties, null, 2);
                            nodePre.innerHTML = `<span class="text-info">:${labelStr}</span> ${propsStr}`;
                            td.appendChild(nodePre);
                        } else if (value.type) {
                            // It's a relationship
                            const relPre = document.createElement('pre');
                            relPre.innerHTML = `<span class="text-warning">:${value.type}</span> ${JSON.stringify(value.properties, null, 2)}`;
                            td.appendChild(relPre);
                        } else {
                            // Other object
                            const objPre = document.createElement('pre');
                            objPre.textContent = JSON.stringify(value, null, 2);
                            td.appendChild(objPre);
                        }
                    } else {
                        td.textContent = value;
                    }
                    
                    row.appendChild(td);
                });
                
                tbody.appendChild(row);
            });
            
            table.appendChild(tbody);
            tableContainer.appendChild(table);
            resultsContainer.appendChild(tableContainer);
            
        } else if (typeof results === 'object') {
            // Handle create/delete operations results
            const resultInfo = document.createElement('div');
            resultInfo.className = 'message-box message-success';
            
            let message = '<i data-feather="check-circle" class="me-2"></i> ';
            
            if (results.created !== undefined) {
                message += `Created ${results.created} node(s)`;
            } else if (results.created_relationships !== undefined) {
                message += `Created ${results.created_relationships} relationship(s)`;
            } else if (results.deleted_nodes !== undefined || results.deleted_relationships !== undefined) {
                const nodesDeleted = results.deleted_nodes || 0;
                const relsDeleted = results.deleted_relationships || 0;
                message += `Deleted ${nodesDeleted} node(s) and ${relsDeleted} relationship(s)`;
            } else {
                message += `Operation completed successfully`;
            }
            
            resultInfo.innerHTML = message;
            resultsContainer.appendChild(resultInfo);
            feather.replace();
        }
    }
    
    // Visualize graph using D3.js
    function visualizeGraph(results) {
        // Extract nodes and relationships from results
        const nodes = [];
        const links = [];
        const nodeMap = {};
        
        // Process each result row
        results.forEach(row => {
            Object.keys(row).forEach(key => {
                const value = row[key];
                
                if (value && typeof value === 'object') {
                    if (value.labels) {
                        // It's a node
                        if (!nodeMap[value.id]) {
                            const labelStr = value.labels.join(':');
                            const node = {
                                id: value.id,
                                labels: value.labels,
                                labelStr: labelStr.length > 0 ? `:${labelStr}` : '',
                                properties: value.properties,
                                // Choose color based on first label
                                color: getNodeColor(value.labels[0] || '')
                            };
                            
                            nodes.push(node);
                            nodeMap[value.id] = node;
                        }
                    } else if (value.type && value.source_id && value.target_id) {
                        // It's a relationship
                        // Only add if both nodes exist
                        if (nodeMap[value.source_id] || nodeMap[value.target_id]) {
                            links.push({
                                id: value.id,
                                source: value.source_id,
                                target: value.target_id,
                                type: value.type,
                                properties: value.properties
                            });
                        }
                    }
                }
            });
        });
        
        // If no nodes found, don't render
        if (nodes.length === 0) {
            return;
        }
        
        // Clear previous visualization
        graphContainer.innerHTML = '';
        
        // Set up D3 force simulation
        const width = graphContainer.clientWidth;
        const height = graphContainer.clientHeight;
        
        const svg = d3.select(graphContainer)
            .append('svg')
            .attr('width', width)
            .attr('height', height);
        
        // Define arrow marker for relationship lines
        svg.append('defs').append('marker')
            .attr('id', 'arrowhead')
            .attr('viewBox', '-0 -5 10 10')
            .attr('refX', 25)
            .attr('refY', 0)
            .attr('orient', 'auto')
            .attr('markerWidth', 6)
            .attr('markerHeight', 6)
            .append('path')
            .attr('d', 'M 0,-5 L 10,0 L 0,5')
            .attr('class', 'relationship-arrow');
        
        // Create force simulation
        const simulation = d3.forceSimulation(nodes)
            .force('link', d3.forceLink(links).id(d => d.id).distance(100))
            .force('charge', d3.forceManyBody().strength(-200))
            .force('center', d3.forceCenter(width / 2, height / 2))
            .force('collision', d3.forceCollide().radius(40));
        
        // Create links
        const link = svg.append('g')
            .selectAll('line')
            .data(links)
            .enter()
            .append('line')
            .attr('class', 'relationship-line')
            .attr('marker-end', 'url(#arrowhead)');
        
        // Create link labels
        const linkText = svg.append('g')
            .selectAll('text')
            .data(links)
            .enter()
            .append('text')
            .attr('class', 'relationship-label')
            .text(d => d.type);
        
        // Create node circles
        const node = svg.append('g')
            .selectAll('circle')
            .data(nodes)
            .enter()
            .append('circle')
            .attr('class', 'node-circle')
            .attr('r', 20)
            .attr('fill', d => d.color)
            .call(d3.drag()
                .on('start', dragStarted)
                .on('drag', dragging)
                .on('end', dragEnded));
        
        // Create node labels
        const nodeText = svg.append('g')
            .selectAll('text')
            .data(nodes)
            .enter()
            .append('text')
            .attr('class', 'node-label')
            .text(d => {
                // Get a good label - try to find a name or title property,
                // or just use first property
                if (d.properties.name) return d.properties.name;
                if (d.properties.title) return d.properties.title;
                
                const propKeys = Object.keys(d.properties);
                if (propKeys.length > 0) {
                    return String(d.properties[propKeys[0]]).substring(0, 10);
                }
                return '';
            });
        
        // Create node type labels
        const nodeTypeText = svg.append('g')
            .selectAll('text')
            .data(nodes)
            .enter()
            .append('text')
            .attr('class', 'node-property')
            .attr('dy', -25)
            .text(d => d.labelStr);
        
        // Update positions on tick
        simulation.on('tick', () => {
            // Constrain nodes to viewport
            nodes.forEach(node => {
                node.x = Math.max(20, Math.min(width - 20, node.x));
                node.y = Math.max(20, Math.min(height - 20, node.y));
            });
            
            link
                .attr('x1', d => d.source.x)
                .attr('y1', d => d.source.y)
                .attr('x2', d => d.target.x)
                .attr('y2', d => d.target.y);
            
            linkText
                .attr('x', d => (d.source.x + d.target.x) / 2)
                .attr('y', d => (d.source.y + d.target.y) / 2 - 5);
            
            node
                .attr('cx', d => d.x)
                .attr('cy', d => d.y);
            
            nodeText
                .attr('x', d => d.x)
                .attr('y', d => d.y + 5);
            
            nodeTypeText
                .attr('x', d => d.x)
                .attr('y', d => d.y);
        });
        
        // Drag functions
        function dragStarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }
        
        function dragging(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }
        
        function dragEnded(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
    }
    
    // Get color for node based on label
    function getNodeColor(label) {
        const colorMap = {
            'Person': '#0d6efd',    // Bootstrap primary
            'Movie': '#fd7e14',     // Bootstrap orange
            'Book': '#198754',      // Bootstrap success
            'Place': '#20c997',     // Bootstrap teal
            'Event': '#d63384',     // Bootstrap pink
            'Company': '#6f42c1',   // Bootstrap purple
            'Product': '#0dcaf0'    // Bootstrap info
        };
        
        return colorMap[label] || '#6c757d'; // Default to secondary color
    }
    
    // Add keyboard shortcut to execute query (Ctrl+Enter)
    queryInput.addEventListener('keydown', function(e) {
        if (e.ctrlKey && e.key === 'Enter') {
            executeBtn.click();
        }
    });
});
